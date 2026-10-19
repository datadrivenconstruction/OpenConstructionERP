# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Flagship demo: Mixed-use high-rise tower, Abu Dhabi (UAE)
# Region AE / locale ar (bilingual EN-AR) / MasterFormat / AED
#
# Program: A landmark mixed-use tower on Al Maryah Island, Abu Dhabi.
# 44 above-grade storeys plus a 4-level retail/F&B podium and 4 basement
# parking levels. Vertical stack: retail podium (L1-L4), Grade-A offices
# (L6-L24), branded serviced residences / hotel keys (L26-L43), with a
# sky lobby and amenity floor at L25 and rooftop plant. Gross floor area
# ~118,000 m2 above grade plus ~46,000 m2 basement (1,250 parking bays).
# Structural system: cast-in-place reinforced-concrete jump-form central
# core with post-tensioned flat slabs and perimeter RC columns; a steel
# transfer/outrigger storey at the podium-to-tower interface. Envelope:
# unitised aluminium-and-glass curtain wall with high-performance solar
# control double glazing (low U-value / low SHGC for the Gulf climate).
# Vertical transportation: destination-control high-speed passenger lifts
# in dedicated rises plus shuttle and service cars, building maintenance
# units (BMU) for facade access. MEP: district cooling (Tabreed) chilled
# water connection, high-rise pressure-zoned domestic water, life-safety
# generators. Compliance: Estidama Pearl Rating System (3 Pearl design
# target) and UAE Fire & Life Safety Code of Practice (Civil Defence),
# ADM / DMT building regulations, ASHRAE 90.1 energy baseline.
# Construction cost order of magnitude ~1.45 B AED direct (Abu Dhabi
# 2026 price level, before 5% VAT), ~1.85 B AED with preliminaries,
# overhead, profit and contingency. FIDIC Red Book (1999) lump-sum.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="tower-abudhabi",
    project_name="Al Maryah Mixed-Use Tower - برج المارية متعدد الاستخدامات",
    project_description=(
        "Landmark mixed-use high-rise on Al Maryah Island, Abu Dhabi: 44 "
        "above-grade storeys over a 4-level retail and F&B podium, with 4 "
        "basement parking levels (1,250 bays). Vertical stack of Grade-A "
        "offices, branded serviced residences and a hotel component, plus a "
        "sky lobby and amenity floor and rooftop plant. Gross floor area "
        "approx. 118,000 m² above grade and 46,000 m² basement. "
        "Cast-in-place reinforced-concrete jump-form central core with "
        "post-tensioned flat slabs and perimeter RC columns; a steel "
        "transfer / outrigger storey at the podium-to-tower interface. "
        "Unitised aluminium-and-glass curtain wall with high-performance "
        "solar-control double glazing for the Gulf climate. Destination-"
        "control high-speed passenger lifts with shuttle and service cars, "
        "and building maintenance units (BMU) for facade access. "
        "High-rise MEP with a district cooling (Tabreed) chilled-water "
        "connection, pressure-zoned domestic water and life-safety "
        "generators. Estidama 3 Pearl design target and full compliance "
        "with the UAE Fire & Life Safety Code of Practice (Civil Defence). "
        "FIDIC Red Book (1999) lump-sum contract. Estimated construction "
        "cost approx. 1.45 B AED direct (Abu Dhabi 2026 price level, before "
        "5% VAT)."
    ),
    region="AE",
    classification_standard="masterformat",
    currency="AED",
    locale="ar",
    address={
        "street": "Al Maryah Island, Sowwah Square",
        "city": "Abu Dhabi",
        "postcode": "",
        "country": "United Arab Emirates",
        "lat": 24.5012,
        "lng": 54.3897,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Detailed Cost Estimate - Mixed-Use Tower (division-based)",
    boq_description=(
        "Detailed cost estimate for the Al Maryah mixed-use tower by standard "
        "division, 03 to 33. Direct costs in AED, before 5% VAT."
    ),
    boq_metadata={
        "standard": "Division-based work-results classification",
        "phase": "Detailed Estimate / Design Development",
        "base_date": "2026-Q2",
        "price_level": "Abu Dhabi 2026",
    },
    sections=[
        # ── 31 Enabling Works, Piling & Shoring ────────────────────────
        (
            "31",
            "Enabling Works, Piling & Shoring",
            {"masterformat": "31 00 00"},
            [
                (
                    "31.1",
                    "Site clearance, hoarding and setting out",
                    "lsum",
                    1,
                    1850000.00,
                    {"masterformat": "31 10 00"},
                ),
                (
                    "31.2",
                    "Bulk excavation to basement formation (4 levels)",
                    "m3",
                    168000,
                    32.00,
                    {"masterformat": "31 23 16"},
                ),
                (
                    "31.3",
                    "Contiguous bored pile shoring wall d=900mm",
                    "m2",
                    9800,
                    685.00,
                    {"masterformat": "31 63 00"},
                ),
                ("31.4", "Anchored capping beam to shoring", "m", 420, 1450.00, {"masterformat": "31 50 00"}),
                ("31.5", "Bored cast-in-situ bearing piles d=1500mm", "m", 12600, 920.00, {"masterformat": "31 63 26"}),
                ("31.6", "Bored cast-in-situ bearing piles d=1200mm", "m", 8400, 720.00, {"masterformat": "31 63 26"}),
                ("31.7", "Pile integrity and static load testing", "pcs", 38, 28500.00, {"masterformat": "31 09 16"}),
                (
                    "31.8",
                    "Dewatering and groundwater control (deep wells)",
                    "lsum",
                    1,
                    2650000.00,
                    {"masterformat": "31 23 19"},
                ),
                ("31.9", "Disposal of excavated material off-site", "m3", 150000, 24.00, {"masterformat": "31 23 23"}),
                (
                    "31.10",
                    "Geotechnical instrumentation and monitoring",
                    "lsum",
                    1,
                    620000.00,
                    {"masterformat": "31 09 00"},
                ),
            ],
        ),
        # ── 03 Concrete - Substructure, Core & PT Slabs ────────────────
        (
            "03",
            "Concrete - Substructure, Core & Post-Tensioned Slabs",
            {"masterformat": "03 00 00"},
            [
                ("03.1", "Blinding concrete C15 below raft", "m3", 1850, 295.00, {"masterformat": "03 30 00"}),
                ("03.2", "Mat / raft foundation C50/60, 3.0m thick", "m3", 28500, 720.00, {"masterformat": "03 30 00"}),
                ("03.3", "Pile caps and ground beams C40", "m3", 4200, 640.00, {"masterformat": "03 30 00"}),
                ("03.4", "Basement perimeter walls C40 watertight", "m3", 9600, 690.00, {"masterformat": "03 30 00"}),
                ("03.5", "Basement and podium suspended slabs C40", "m3", 18500, 610.00, {"masterformat": "03 30 00"}),
                ("03.6", "Jump-form RC core walls C60 high-rise", "m3", 22500, 880.00, {"masterformat": "03 30 00"}),
                ("03.7", "Perimeter and internal columns C60-C70", "m3", 9800, 950.00, {"masterformat": "03 30 00"}),
                (
                    "03.8",
                    "Post-tensioned flat slabs typical floors C45",
                    "m2",
                    96000,
                    285.00,
                    {"masterformat": "03 38 00"},
                ),
                ("03.9", "PT tendons supply, install and stress", "t", 1120, 9800.00, {"masterformat": "03 38 00"}),
                (
                    "03.10",
                    "Reinforcement steel B500B supply and fix",
                    "t",
                    18600,
                    3450.00,
                    {"masterformat": "03 21 00"},
                ),
                (
                    "03.11",
                    "Jump-form system to core (hire and operation)",
                    "m2",
                    26000,
                    165.00,
                    {"masterformat": "03 11 00"},
                ),
                ("03.12", "Wall and column formwork", "m2", 64000, 92.00, {"masterformat": "03 11 00"}),
                ("03.13", "Slab soffit formwork and flying tables", "m2", 112000, 78.00, {"masterformat": "03 11 00"}),
                ("03.14", "Concrete pumping and high-rise placement", "m3", 95000, 38.00, {"masterformat": "03 31 00"}),
                ("03.15", "Power-float and curing to slabs", "m2", 132000, 16.50, {"masterformat": "03 35 00"}),
            ],
        ),
        # ── 05 Metals - Steel Transfer, Outrigger & Misc ───────────────
        (
            "05",
            "Metals - Steel Transfer, Outrigger & Miscellaneous",
            {"masterformat": "05 00 00"},
            [
                (
                    "05.1",
                    "Structural steel transfer trusses (podium interface)",
                    "t",
                    1450,
                    12500.00,
                    {"masterformat": "05 12 00"},
                ),
                ("05.2", "Outrigger and belt-truss steelwork", "t", 980, 13200.00, {"masterformat": "05 12 00"}),
                (
                    "05.3",
                    "Composite steel deck to amenity / plant floors",
                    "m2",
                    7200,
                    165.00,
                    {"masterformat": "05 31 00"},
                ),
                ("05.4", "Steel framing to canopy and feature roof", "t", 320, 11800.00, {"masterformat": "05 12 00"}),
                (
                    "05.5",
                    "Galvanised steel stairs and landings (fire stairs)",
                    "pcs",
                    96,
                    22500.00,
                    {"masterformat": "05 51 00"},
                ),
                (
                    "05.6",
                    "Stainless and glass balustrades and handrails",
                    "m",
                    4200,
                    1450.00,
                    {"masterformat": "05 52 13"},
                ),
                ("05.7", "Spray-applied fire protection to steel", "m2", 28000, 92.00, {"masterformat": "05 12 00"}),
                ("05.8", "Miscellaneous metalwork and embeds", "t", 185, 9800.00, {"masterformat": "05 50 00"}),
            ],
        ),
        # ── 07 Thermal & Moisture Protection ───────────────────────────
        (
            "07",
            "Thermal & Moisture Protection",
            {"masterformat": "07 00 00"},
            [
                (
                    "07.1",
                    "Tanking / waterproofing to raft and basement walls",
                    "m2",
                    38000,
                    145.00,
                    {"masterformat": "07 13 00"},
                ),
                (
                    "07.2",
                    "Hot-applied waterproofing to podium decks",
                    "m2",
                    14500,
                    185.00,
                    {"masterformat": "07 14 00"},
                ),
                (
                    "07.3",
                    "Exposed roof membrane and insulation system",
                    "m2",
                    4800,
                    220.00,
                    {"masterformat": "07 54 00"},
                ),
                ("07.4", "Thermal insulation to soffits and risers", "m2", 22000, 48.00, {"masterformat": "07 21 00"}),
                (
                    "07.5",
                    "Air and vapour barrier to back-of-house facades",
                    "m2",
                    9600,
                    62.00,
                    {"masterformat": "07 27 00"},
                ),
                ("07.6", "Firestopping to service penetrations", "lsum", 1, 2850000.00, {"masterformat": "07 84 00"}),
                ("07.7", "Joint sealants and weatherproofing", "m", 18500, 38.00, {"masterformat": "07 92 00"}),
                (
                    "07.8",
                    "Cementitious and intumescent fireproofing (cores)",
                    "m2",
                    12000,
                    78.00,
                    {"masterformat": "07 81 00"},
                ),
            ],
        ),
        # ── 08 Openings & Curtain-Wall Facade ──────────────────────────
        (
            "08",
            "Openings & Curtain-Wall Facade",
            {"masterformat": "08 00 00"},
            [
                (
                    "08.1",
                    "Unitised curtain wall, solar-control DGU (tower)",
                    "m2",
                    62000,
                    1850.00,
                    {"masterformat": "08 44 13"},
                ),
                (
                    "08.2",
                    "Stick-system curtain wall and shopfronts (podium)",
                    "m2",
                    14500,
                    1450.00,
                    {"masterformat": "08 44 00"},
                ),
                ("08.3", "Spandrel and shadow-box panels", "m2", 9800, 980.00, {"masterformat": "08 44 00"}),
                ("08.4", "Feature crown / parapet cladding", "m2", 3200, 2200.00, {"masterformat": "08 44 00"}),
                ("08.5", "Automatic glazed entrance portals", "pcs", 8, 145000.00, {"masterformat": "08 42 29"}),
                ("08.6", "Hollow metal doors and frames", "pcs", 1850, 1450.00, {"masterformat": "08 11 13"}),
                (
                    "08.7",
                    "Timber veneer doors to apartments / offices",
                    "pcs",
                    2400,
                    1650.00,
                    {"masterformat": "08 14 16"},
                ),
                ("08.8", "Fire-rated doors 60/120 min", "pcs", 1100, 2850.00, {"masterformat": "08 11 13"}),
                ("08.9", "Architectural ironmongery sets", "pcs", 5350, 920.00, {"masterformat": "08 71 00"}),
                ("08.10", "Internal glazed partitions and screens", "m2", 12500, 680.00, {"masterformat": "08 80 00"}),
                ("08.11", "Louvres to plant and BOH areas", "m2", 2600, 720.00, {"masterformat": "08 90 00"}),
            ],
        ),
        # ── 09 Finishes ────────────────────────────────────────────────
        (
            "09",
            "Finishes",
            {"masterformat": "09 00 00"},
            [
                ("09.1", "Metal-stud and gypsum partitions", "m2", 96000, 165.00, {"masterformat": "09 21 16"}),
                ("09.2", "Suspended acoustic and gypsum ceilings", "m2", 88000, 185.00, {"masterformat": "09 51 00"}),
                ("09.3", "Raised access flooring to office floors", "m2", 42000, 245.00, {"masterformat": "09 69 00"}),
                ("09.4", "Porcelain and natural stone floor tiling", "m2", 38000, 320.00, {"masterformat": "09 30 00"}),
                ("09.5", "Ceramic wall tiling to wet areas", "m2", 24000, 165.00, {"masterformat": "09 30 00"}),
                ("09.6", "Carpet and resilient flooring", "m2", 36000, 145.00, {"masterformat": "09 68 00"}),
                ("09.7", "Stone cladding to lobby and lift cores", "m2", 8600, 685.00, {"masterformat": "09 75 00"}),
                (
                    "09.8",
                    "Joinery and wall panelling (lobbies / sky lobby)",
                    "m2",
                    5200,
                    920.00,
                    {"masterformat": "06 40 00"},
                ),
                ("09.9", "Painting and decorative finishes", "m2", 165000, 48.00, {"masterformat": "09 91 00"}),
                ("09.10", "Epoxy floor coating to basement / plant", "m2", 46000, 62.00, {"masterformat": "09 67 00"}),
                ("09.11", "Screeds and floor levelling", "m2", 132000, 42.00, {"masterformat": "09 24 00"}),
                (
                    "09.12",
                    "Acoustic treatment to residential demising walls",
                    "m2",
                    18000,
                    98.00,
                    {"masterformat": "09 84 00"},
                ),
            ],
        ),
        # ── 10 / 12 Specialties, FF&E & Fit-out ────────────────────────
        (
            "10",
            "Specialties, FF&E & Fit-out",
            {"masterformat": "10 00 00"},
            [
                (
                    "10.1",
                    "Toilet cubicles, IPS panels and washroom fit-out",
                    "lsum",
                    1,
                    6800000.00,
                    {"masterformat": "10 21 13"},
                ),
                (
                    "10.2",
                    "Signage and wayfinding (statutory and amenity)",
                    "lsum",
                    1,
                    2400000.00,
                    {"masterformat": "10 14 00"},
                ),
                ("10.3", "Fitted kitchens to serviced residences", "pcs", 280, 38000.00, {"masterformat": "12 35 30"}),
                (
                    "10.4",
                    "Built-in wardrobes and joinery to apartments",
                    "pcs",
                    280,
                    22500.00,
                    {"masterformat": "12 32 00"},
                ),
                ("10.5", "Window roller blinds and solar shading", "m2", 24000, 165.00, {"masterformat": "12 24 00"}),
                (
                    "10.6",
                    "Lobby and amenity loose furniture (FF&E)",
                    "lsum",
                    1,
                    9500000.00,
                    {"masterformat": "12 50 00"},
                ),
                ("10.7", "Window cleaning rail and anchor system", "lsum", 1, 1650000.00, {"masterformat": "11 24 00"}),
            ],
        ),
        # ── 14 Conveying - Lifts, Escalators & BMU ─────────────────────
        (
            "14",
            "Conveying - Lifts, Escalators & BMU",
            {"masterformat": "14 00 00"},
            [
                (
                    "14.1",
                    "High-speed passenger lifts 4.0 m/s, destination control",
                    "pcs",
                    14,
                    1850000.00,
                    {"masterformat": "14 21 00"},
                ),
                ("14.2", "Shuttle lifts to sky lobby 6.0 m/s", "pcs", 4, 2650000.00, {"masterformat": "14 21 00"}),
                ("14.3", "Service / fire-fighting lifts", "pcs", 4, 1450000.00, {"masterformat": "14 21 00"}),
                ("14.4", "Parking and podium lifts", "pcs", 6, 685000.00, {"masterformat": "14 24 00"}),
                ("14.5", "Escalators to retail podium", "pcs", 12, 320000.00, {"masterformat": "14 31 00"}),
                (
                    "14.6",
                    "Building maintenance units (BMU) roof cradles",
                    "pcs",
                    3,
                    2850000.00,
                    {"masterformat": "14 84 00"},
                ),
            ],
        ),
        # ── 21 Fire Suppression / Life Safety ──────────────────────────
        (
            "21",
            "Fire Suppression & Life Safety",
            {"masterformat": "21 00 00"},
            [
                (
                    "21.1",
                    "Automatic sprinkler system (high-rise zoned)",
                    "m2",
                    164000,
                    62.00,
                    {"masterformat": "21 13 00"},
                ),
                ("21.2", "Wet and dry risers and landing valves", "m", 1850, 420.00, {"masterformat": "21 12 00"}),
                ("21.3", "Fire pumps (electric + diesel + jockey)", "pcs", 3, 685000.00, {"masterformat": "21 30 00"}),
                (
                    "21.4",
                    "Gaseous suppression to electrical / IT rooms",
                    "lsum",
                    1,
                    2850000.00,
                    {"masterformat": "21 22 00"},
                ),
                (
                    "21.5",
                    "Stair pressurisation and smoke control fans",
                    "pcs",
                    48,
                    78000.00,
                    {"masterformat": "23 34 00"},
                ),
                (
                    "21.6",
                    "Fire hose cabinets and portable extinguishers",
                    "pcs",
                    520,
                    1850.00,
                    {"masterformat": "21 10 00"},
                ),
            ],
        ),
        # ── 22 Plumbing & Drainage (High-Rise) ─────────────────────────
        (
            "22",
            "Plumbing & Drainage (High-Rise)",
            {"masterformat": "22 00 00"},
            [
                (
                    "22.1",
                    "Pressure-zoned domestic cold water (tanks + pumps)",
                    "lsum",
                    1,
                    8600000.00,
                    {"masterformat": "22 11 00"},
                ),
                ("22.2", "Hot water generation and circulation", "lsum", 1, 4200000.00, {"masterformat": "22 34 00"}),
                (
                    "22.3",
                    "Soil, waste and vent stacks (cast iron / HDPE)",
                    "m",
                    18500,
                    165.00,
                    {"masterformat": "22 13 00"},
                ),
                ("22.4", "Internal storm and condensate drainage", "m", 9600, 145.00, {"masterformat": "22 14 00"}),
                (
                    "22.5",
                    "Sanitary fixtures and brassware (complete)",
                    "pcs",
                    4200,
                    2200.00,
                    {"masterformat": "22 40 00"},
                ),
                (
                    "22.6",
                    "Treated sewage effluent (TSE) irrigation supply",
                    "lsum",
                    1,
                    1650000.00,
                    {"masterformat": "22 13 00"},
                ),
                ("22.7", "Submersible pumps to basement sumps", "pcs", 24, 28500.00, {"masterformat": "22 14 29"}),
            ],
        ),
        # ── 23 HVAC & District Cooling ─────────────────────────────────
        (
            "23",
            "HVAC & District Cooling",
            {"masterformat": "23 00 00"},
            [
                (
                    "23.1",
                    "District cooling (Tabreed) energy transfer station",
                    "lsum",
                    1,
                    14500000.00,
                    {"masterformat": "23 21 13"},
                ),
                ("23.2", "Chilled water risers and secondary pumping", "m", 6800, 420.00, {"masterformat": "23 21 00"}),
                ("23.3", "Air handling units with heat recovery", "pcs", 64, 165000.00, {"masterformat": "23 73 00"}),
                ("23.4", "Fan coil units to apartments / offices", "pcs", 3200, 4200.00, {"masterformat": "23 82 19"}),
                ("23.5", "Ductwork supply and install (galvanised)", "kg", 420000, 14.50, {"masterformat": "23 31 00"}),
                (
                    "23.6",
                    "Basement and podium car-park ventilation (jet fans)",
                    "pcs",
                    120,
                    28500.00,
                    {"masterformat": "23 34 00"},
                ),
                ("23.7", "Diffusers, grilles and VAV terminals", "pcs", 6800, 320.00, {"masterformat": "23 37 00"}),
                (
                    "23.8",
                    "Building management system (BMS) and controls",
                    "lsum",
                    1,
                    9800000.00,
                    {"masterformat": "23 09 00"},
                ),
                (
                    "23.9",
                    "Testing, adjusting, balancing and commissioning",
                    "lsum",
                    1,
                    4200000.00,
                    {"masterformat": "23 05 93"},
                ),
            ],
        ),
        # ── 26 / 27 / 28 Electrical, ICT & Security ────────────────────
        (
            "26",
            "Electrical, ICT & Security",
            {"masterformat": "26 00 00"},
            [
                (
                    "26.1",
                    "HV intake, ring main units and substations",
                    "lsum",
                    1,
                    18500000.00,
                    {"masterformat": "26 11 00"},
                ),
                ("26.2", "Distribution transformers 1500 kVA", "pcs", 12, 285000.00, {"masterformat": "26 22 00"}),
                (
                    "26.3",
                    "Standby diesel generators 2000 kVA + ATS",
                    "pcs",
                    3,
                    1450000.00,
                    {"masterformat": "26 32 13"},
                ),
                (
                    "26.4",
                    "Main and sub-main LV distribution boards",
                    "pcs",
                    240,
                    38000.00,
                    {"masterformat": "26 24 16"},
                ),
                ("26.5", "Busbar risers (vertical distribution)", "m", 2400, 1850.00, {"masterformat": "26 25 00"}),
                ("26.6", "Cable containment, trays and conduits", "m", 96000, 92.00, {"masterformat": "26 05 33"}),
                ("26.7", "Power and lighting final circuit wiring", "m", 620000, 22.00, {"masterformat": "26 05 19"}),
                ("26.8", "LED luminaires and emergency lighting", "pcs", 38000, 285.00, {"masterformat": "26 51 00"}),
                ("26.9", "Lighting control and DALI system", "lsum", 1, 6800000.00, {"masterformat": "26 09 23"}),
                (
                    "26.10",
                    "Earthing, bonding and lightning protection",
                    "lsum",
                    1,
                    3200000.00,
                    {"masterformat": "26 41 00"},
                ),
                (
                    "26.11",
                    "Structured cabling and ICT backbone (Cat 6A / fibre)",
                    "lsum",
                    1,
                    9800000.00,
                    {"masterformat": "27 10 00"},
                ),
                (
                    "26.12",
                    "CCTV, access control and security system",
                    "lsum",
                    1,
                    7200000.00,
                    {"masterformat": "28 20 00"},
                ),
                (
                    "26.13",
                    "Fire detection and voice alarm (addressable)",
                    "lsum",
                    1,
                    8600000.00,
                    {"masterformat": "28 31 00"},
                ),
                ("26.14", "EV charging stations to car park", "pcs", 120, 12500.00, {"masterformat": "26 27 00"}),
            ],
        ),
        # ── 32 / 33 External Works & Utilities ─────────────────────────
        (
            "32",
            "External Works & Utilities",
            {"masterformat": "32 00 00"},
            [
                ("32.1", "Hard landscaping, paving and plaza decks", "m2", 14500, 320.00, {"masterformat": "32 14 00"}),
                ("32.2", "Soft landscaping and podium planting", "m2", 6800, 245.00, {"masterformat": "32 90 00"}),
                ("32.3", "TSE drip irrigation and water features", "lsum", 1, 2650000.00, {"masterformat": "32 84 00"}),
                (
                    "32.4",
                    "External lighting and feature facade lighting",
                    "pcs",
                    280,
                    6800.00,
                    {"masterformat": "26 56 00"},
                ),
                (
                    "32.5",
                    "External infrastructure and utility diversions",
                    "lsum",
                    1,
                    4800000.00,
                    {"masterformat": "33 00 00"},
                ),
                ("32.6", "Stormwater attenuation and connection", "m", 1200, 420.00, {"masterformat": "33 40 00"}),
                ("32.7", "Site boundary, gates and guardhouse", "lsum", 1, 1850000.00, {"masterformat": "32 31 00"}),
            ],
        ),
    ],
    markups=[
        ("Preliminaries & General (P&G)", 12.0, "overhead", "direct_cost"),
        ("Main Contractor Overhead", 6.0, "overhead", "direct_cost"),
        ("Main Contractor Profit", 7.0, "profit", "direct_cost"),
        ("Design Development Contingency", 5.0, "contingency", "cumulative"),
        ("VAT (UAE, 5%)", 5.0, "tax", "cumulative"),
    ],
    total_months=42,
    tender_name="Main Construction Package (Structure, Facade & MEP)",
    tender_companies=[
        ("AVEN Engineering & Contracting", "tenders@aven.example", 0.98),
        ("Karnath General Contracting", "bids@karnath.example", 1.05),
        ("Seven Construct (Bervax Group)", "tender@sevenconstruct.example", 1.02),
        ("Zumratec Construction", "procurement@zumratec.example", 1.07),
    ],
    project_metadata={
        "address": "Al Maryah Island, Sowwah Square, Abu Dhabi, UAE",
        "client": "Nawaris Island Development PJSC",
        "architect": "Trenholme Middle East",
        "structural_engineer": "Norvenor Middle East",
        "mep_engineer": "Hensford Gulf Engineering",
        "general_contractor_form": "FIDIC Red Book (1999) - lump-sum contract",
        "gfa_above_grade_m2": 118000,
        "gfa_basement_m2": 46000,
        "storeys": 44,
        "podium_levels": 4,
        "basement_levels": 4,
        "parking_spaces": 1250,
        "use_mix": "Retail/F&B podium + Grade-A offices + branded serviced residences / hotel",
        "structure_system": (
            "Jump-form RC core with post-tensioned flat slabs and perimeter "
            "RC columns; steel transfer / outrigger storey at podium interface"
        ),
        "facade_system": "Unitised aluminium-and-glass curtain wall, solar-control DGU",
        "codes": [
            "UAE Fire & Life Safety Code of Practice (Civil Defence)",
            "Abu Dhabi International Building Code (ADIBC) / IBC basis",
            "Estidama Pearl Rating System (Pearl Building Rating)",
            "ASHRAE 90.1 energy baseline",
            "ACI 318 / BS EN 1992 concrete design basis",
        ],
        "permits": (
            "Abu Dhabi Municipality (ADM/DMT) building permit; Abu Dhabi "
            "Civil Defence approval; Estidama Pearl design rating; ADDC and "
            "Tabreed district cooling NOCs."
        ),
        "sustainability": "Estidama 3 Pearl design rating target; LEED v4 BD+C alignment",
        "vertical_transport": (
            "Destination-control high-speed passenger lifts (4.0-6.0 m/s) in "
            "dedicated rises, shuttle and service cars, plus roof BMU"
        ),
        "cooling": "District cooling (Tabreed) chilled-water connection via energy transfer station",
        "taxes_note": (
            "UAE VAT at 5% is applied as a final markup; the priced positions are direct costs excluding VAT."
        ),
    },
    tender_packages=[
        (
            "Enabling, Piling & Substructure",
            "Excavation, shoring, bored piles, dewatering, raft and basement structure",
            "evaluating",
            [
                ("AVEN Engineering & Contracting", "tenders@aven.example", 0.98),
                ("Karnath General Contracting", "bids@karnath.example", 1.05),
                ("Grundwerk International FZE", "tender@grundwerk.example", 1.01),
            ],
        ),
        (
            "Superstructure (Core & PT Slabs)",
            "Jump-form RC core, post-tensioned flat slabs, columns and steel transfer works",
            "evaluating",
            [
                ("Seven Construct (Bervax Group)", "tender@sevenconstruct.example", 1.02),
                ("AVEN Engineering & Contracting", "tenders@aven.example", 0.99),
                ("Zumratec Construction", "procurement@zumratec.example", 1.06),
            ],
        ),
        (
            "Facade (Unitised Curtain Wall)",
            "Tower unitised curtain wall, podium shopfronts, spandrels and feature crown",
            "evaluating",
            [
                ("Alumvest LLC", "estimation@alumvest.example", 0.97),
                ("Sarwellan Glazing Industrial", "tenders@sarwellan.example", 1.04),
                ("Vitrolam / Hallensen Gulf", "bids@vitrolam.example", 1.02),
            ],
        ),
        (
            "MEP & District Cooling",
            "HVAC, district cooling ETS, plumbing, fire suppression, BMS and commissioning",
            "evaluating",
            [
                ("Thermoya Limited (Gulf)", "tenders@thermoya-gulf.example", 0.99),
                ("Mirvane Air Conditioning", "estimation@mirvane.example", 1.05),
                ("Nakhbara International", "bids@nakhbara.example", 1.03),
            ],
        ),
        (
            "Electrical, ICT & Vertical Transport",
            "HV/LV distribution, generators, ELV/security, fire alarm and lifts/escalators",
            "evaluating",
            [
                ("Oryx Crest / Oryx M&E", "tenders@oryxcrest.example", 0.98),
                ("Al-Nahzari Engineering", "estimation@alnahzari.example", 1.05),
                ("Orvenda Middle East (lifts)", "bids@orvenda-me.example", 1.02),
            ],
        ),
        (
            "Fit-out & External Works",
            "Internal finishes, FF&E, landscaping, plaza decks and site infrastructure",
            "evaluating",
            [
                ("Rehan Interiors LLC", "tenders@rehan.example", 0.99),
                ("Palmcourt Interiors", "estimation@palmcourt.example", 1.06),
                ("Dunevale Landscape LLC", "bids@dunevale.example", 1.01),
            ],
        ),
    ],
    budget_boq_name="Al Maryah Mixed-Use Tower - Budget Estimate (AED)",
    planned_budget=1_850_000_000,
    actual_spend_ratio=0.38,
    spi_override=0.97,
    cpi_override=1.02,
)
