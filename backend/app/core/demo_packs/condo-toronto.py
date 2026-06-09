from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Flagship demo: Residential high-rise condominium, Toronto (Ontario, Canada)
# Pack: en-CA / CAD / MasterFormat 2020 / CWICR region CA_TORONTO
#
# Program: 45-storey market condominium tower over a 6-storey podium, 412
# residential suites, ground-floor retail, a podium-level amenity floor
# (fitness, party room, co-work lounge, outdoor terrace) and 4 below-grade
# parking levels (318 stalls + bicycle and locker rooms). GFA ~38 600 m2
# above grade, ~14 200 m2 below grade. Cast-in-place reinforced-concrete
# flat-plate structure with a central shear-wall core (CSA A23.3), post-
# tensioned transfer slab at the podium, window-wall (slab-edge) envelope.
# Built to NBC 2020 as adopted through the Ontario Building Code (OBC,
# O. Reg. 332/12) and the Toronto Green Standard (TGS) Version 4 Tier 1.
# Seismic: NBC 2020 Site Class D, Toronto low-to-moderate seismicity.
# Construction cost ~228 M CAD direct (Toronto Q1-2026 price level, before
# taxes), ~291 M CAD with General Conditions / Overhead & Profit /
# contingency. Stipulated-price contract CCDC 2 (2020).
# Toronto CWICR cost region: CA_TORONTO.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="condo-toronto",
    project_name="Condominium Tower - Toronto, King West",
    project_description=(
        "Market residential high-rise condominium, 45 storeys above a "
        "6-storey podium, with 412 suites, ground-floor retail and a "
        "podium amenity floor (fitness, party room, co-work lounge and "
        "outdoor terrace). Four below-grade parking levels with 318 stalls "
        "plus bicycle and storage-locker rooms. Above-grade GFA approx. "
        "38,600 m2; below-grade approx. 14,200 m2. Cast-in-place reinforced-"
        "concrete flat-plate structure with a central shear-wall core "
        "(CSA A23.3) and a post-tensioned transfer slab at the podium. "
        "Window-wall (slab-edge) envelope with insulated spandrel and "
        "operable vents. Built to NBC 2020 as adopted through the Ontario "
        "Building Code (OBC, O. Reg. 332/12) and Toronto Green Standard "
        "Version 4, Tier 1. Site Class D, Toronto seismic region. "
        "Stipulated-price contract CCDC 2 (2020). Construction cost approx. "
        "228 M CAD in direct costs (~291 M CAD with general conditions, "
        "overhead, profit and contingency; Toronto 2026 price level, before "
        "HST). Cost region: CA_TORONTO."
    ),
    region="CA",
    classification_standard="masterformat",
    currency="CAD",
    locale="en-CA",
    address={
        "street": "85 Bathurst Street",
        "city": "Toronto",
        "postcode": "M5V 0L9",
        "country": "Canada",
        "lat": 43.6433,
        "lng": -79.4019,
    },
    validation_rule_sets=["masterformat", "boq_quality", "project_completeness"],
    boq_name="Detailed Estimate - MasterFormat 2020",
    boq_description=(
        "Class B elemental/trade estimate to MasterFormat 2020, divisions "
        "03 through 32. Direct costs in CAD, Toronto 2026 price level, "
        "before HST."
    ),
    boq_metadata={
        "standard": "MasterFormat 2020",
        "phase": "Class B estimate / Design Development (DD)",
        "base_date": "2026-Q1",
        "price_level": "Toronto 2026",
        "cost_region": "CA_TORONTO",
    },
    sections=[
        # ── Division 31 - Earthwork & Shoring ──────────────────────────
        (
            "31",
            "Division 31 - Earthwork & Shoring",
            {"masterformat": "31 00 00"},
            [
                ("31.1", "Site clearing and grubbing", "lsum", 1, 165000.00, {"masterformat": "31 10 00"}),
                ("31.2", "Mass excavation, soil to 4 parking levels", "m3", 68000, 24.50, {"masterformat": "31 23 16"}),
                ("31.3", "Rock excavation, Georgian Bay shale", "m3", 4200, 165.00, {"masterformat": "31 23 16"}),
                ("31.4", "Caisson wall shoring with steel soldier piles", "m2", 9800, 295.00, {"masterformat": "31 50 00"}),
                ("31.5", "Lagging between soldier piles", "m2", 9800, 78.00, {"masterformat": "31 50 00"}),
                ("31.6", "Tieback anchors, prestressed", "pcs", 186, 5400.00, {"masterformat": "31 51 00"}),
                ("31.7", "Construction dewatering and discharge", "lsum", 1, 420000.00, {"masterformat": "31 23 19"}),
                ("31.8", "Engineered granular backfill, compacted", "m3", 9600, 42.00, {"masterformat": "31 23 23"}),
                ("31.9", "Excavated soil haul and disposal", "m3", 60000, 32.00, {"masterformat": "31 23 23"}),
                ("31.10", "Excess Soil Quality Standards (ESQS) testing", "lsum", 1, 95000.00, {"masterformat": "31 25 00"}),
                ("31.11", "Contaminated soil management, brownfield infill", "t", 5200, 110.00, {"masterformat": "31 25 00"}),
                ("31.12", "Geotechnical investigation and instrumentation", "lsum", 1, 78000.00, {"masterformat": "31 09 00"}),
            ],
        ),
        # ── Division 03 - Concrete ─────────────────────────────────────
        (
            "03",
            "Division 03 - Concrete",
            {"masterformat": "03 00 00"},
            [
                ("03.1", "Blinding concrete, 15 MPa", "m3", 980, 225.00, {"masterformat": "03 30 00"}),
                ("03.2", "Mat foundation slab, 35 MPa, 1500 mm", "m3", 11800, 305.00, {"masterformat": "03 30 00"}),
                ("03.3", "Footings and pile caps, 30 MPa", "m3", 2400, 295.00, {"masterformat": "03 30 00"}),
                ("03.4", "Watertight basement walls, 35 MPa", "m3", 4600, 355.00, {"masterformat": "03 30 00"}),
                ("03.5", "Columns, 50 MPa high-strength", "m3", 3200, 445.00, {"masterformat": "03 30 00"}),
                ("03.6", "Flat-plate suspended slabs, 35 MPa", "m3", 18600, 285.00, {"masterformat": "03 30 00"}),
                ("03.7", "Shear-wall / elevator core, 50 MPa", "m3", 6400, 425.00, {"masterformat": "03 30 00"}),
                ("03.8", "Post-tensioned podium transfer slab, 40 MPa", "m3", 2800, 395.00, {"masterformat": "03 30 00"}),
                ("03.9", "Post-tensioning tendons, supply and stress", "t", 96, 8200.00, {"masterformat": "03 38 00"}),
                ("03.10", "Wall and core formwork, gang/jump form", "m2", 62000, 72.00, {"masterformat": "03 11 00"}),
                ("03.11", "Suspended slab formwork, flying tables", "m2", 168000, 58.00, {"masterformat": "03 11 00"}),
                ("03.12", "Column formwork", "m2", 14200, 78.00, {"masterformat": "03 11 00"}),
                ("03.13", "Reinforcing steel 400W, placed", "t", 6800, 2450.00, {"masterformat": "03 21 00"}),
                ("03.14", "Welded wire reinforcement", "m2", 172000, 9.20, {"masterformat": "03 22 00"}),
                ("03.15", "Trowelled slab finish to suites", "m2", 158000, 11.50, {"masterformat": "03 35 00"}),
                ("03.16", "Hardened quartz floor finish, parking", "m2", 52000, 14.80, {"masterformat": "03 35 00"}),
                ("03.17", "Concrete cure and seal", "m2", 210000, 4.20, {"masterformat": "03 39 00"}),
            ],
        ),
        # ── Division 04 - Masonry ──────────────────────────────────────
        (
            "04",
            "Division 04 - Masonry",
            {"masterformat": "04 00 00"},
            [
                ("04.1", "Concrete block 190 mm, stair and service shafts", "m2", 14800, 158.00, {"masterformat": "04 22 00"}),
                ("04.2", "Concrete block 140 mm, suite demising/party walls", "m2", 9200, 142.00, {"masterformat": "04 22 00"}),
                ("04.3", "Clay brick veneer, podium street facade", "m2", 4200, 295.00, {"masterformat": "04 21 13"}),
                ("04.4", "Architectural cast-stone base and banding", "m2", 680, 565.00, {"masterformat": "04 72 00"}),
                ("04.5", "Masonry joint reinforcement and ties", "m2", 24000, 9.80, {"masterformat": "04 05 23"}),
                ("04.6", "Precast lintels and sills", "m", 920, 98.00, {"masterformat": "04 05 00"}),
            ],
        ),
        # ── Division 05 - Metals ───────────────────────────────────────
        (
            "05",
            "Division 05 - Metals",
            {"masterformat": "05 00 00"},
            [
                ("05.1", "Structural steel, podium retail and canopy framing", "t", 320, 5400.00, {"masterformat": "05 12 00"}),
                ("05.2", "Steel roof deck, mechanical penthouse", "m2", 2400, 42.00, {"masterformat": "05 31 00"}),
                ("05.3", "Egress stairs, steel pan with concrete fill", "pcs", 96, 9200.00, {"masterformat": "05 51 00"}),
                ("05.4", "Balcony guard, aluminum frame with glass infill", "m", 8400, 285.00, {"masterformat": "05 52 13"}),
                ("05.5", "Interior and stair guardrails / handrails", "m", 2200, 245.00, {"masterformat": "05 52 00"}),
                ("05.6", "Miscellaneous metals and embeds", "t", 86, 6800.00, {"masterformat": "05 50 00"}),
                ("05.7", "Galvanized grating and access hatches", "m2", 380, 320.00, {"masterformat": "05 53 00"}),
                ("05.8", "Architecturally exposed entry feature steel", "t", 18, 12500.00, {"masterformat": "05 12 00"}),
            ],
        ),
        # ── Division 07 - Thermal & Moisture / Window-Wall ─────────────
        (
            "07",
            "Division 07 - Thermal & Moisture Protection",
            {"masterformat": "07 00 00"},
            [
                ("07.1", "Bentonite waterproofing, below-grade walls", "m2", 11200, 62.00, {"masterformat": "07 13 00"}),
                ("07.2", "Below-slab vapour and methane barrier", "m2", 9600, 28.00, {"masterformat": "07 26 00"}),
                ("07.3", "Self-adhered air/vapour barrier, podium", "m2", 9800, 26.00, {"masterformat": "07 27 00"}),
                ("07.4", "Continuous rigid exterior insulation, R-25", "m2", 9800, 42.00, {"masterformat": "07 21 00"}),
                ("07.5", "Spandrel-zone semi-rigid insulation, tower", "m2", 22000, 24.00, {"masterformat": "07 21 00"}),
                ("07.6", "Two-ply SBS roofing, podium and main roof", "m2", 6800, 92.00, {"masterformat": "07 52 00"}),
                ("07.7", "Roof insulation, tapered polyiso R-35", "m2", 6800, 58.00, {"masterformat": "07 22 00"}),
                ("07.8", "Extensive green roof, amenity terrace", "m2", 1400, 175.00, {"masterformat": "07 55 63"}),
                ("07.9", "Protected-membrane terrace pavers on pedestals", "m2", 1800, 145.00, {"masterformat": "07 55 00"}),
                ("07.10", "Sheet-metal flashing and copings", "m", 3200, 64.00, {"masterformat": "07 62 00"}),
                ("07.11", "Joint sealants, interior and exterior", "m", 16800, 14.80, {"masterformat": "07 92 00"}),
                ("07.12", "Firestopping at floor and wall penetrations", "lsum", 1, 420000.00, {"masterformat": "07 84 00"}),
                ("07.13", "Spray fireproofing, transfer level steel", "m2", 4200, 19.50, {"masterformat": "07 81 00"}),
            ],
        ),
        # ── Division 08 - Openings (incl. Window-Wall) ─────────────────
        (
            "08",
            "Division 08 - Openings",
            {"masterformat": "08 00 00"},
            [
                ("08.1", "Window-wall system, tower (slab-edge, operable vent)", "m2", 34000, 565.00, {"masterformat": "08 43 00"}),
                ("08.2", "Insulated spandrel panels, window-wall", "m2", 9800, 320.00, {"masterformat": "08 44 00"}),
                ("08.3", "Unitized curtain wall, podium and lobby", "m2", 3800, 695.00, {"masterformat": "08 44 00"}),
                ("08.4", "Storefront glazing, ground-floor retail", "m2", 1200, 480.00, {"masterformat": "08 41 13"}),
                ("08.5", "Automatic sliding entrances, residential lobby", "pcs", 3, 19500.00, {"masterformat": "08 42 29"}),
                ("08.6", "Balcony swing/sliding doors, thermally broken", "pcs", 624, 2850.00, {"masterformat": "08 52 00"}),
                ("08.7", "Suite entry doors, fire-rated solid core", "pcs", 412, 1450.00, {"masterformat": "08 14 16"}),
                ("08.8", "Hollow metal doors and frames, BOH/service", "pcs", 340, 1280.00, {"masterformat": "08 11 13"}),
                ("08.9", "Interior wood doors, suite interiors", "pcs", 1850, 720.00, {"masterformat": "08 14 16"}),
                ("08.10", "90-minute fire doors, stair and shaft", "pcs", 188, 1850.00, {"masterformat": "08 11 13"}),
                ("08.11", "Finish hardware, all doors", "pcs", 3203, 540.00, {"masterformat": "08 71 00"}),
                ("08.12", "Overhead coiling doors, parking and loading", "pcs", 6, 12500.00, {"masterformat": "08 33 00"}),
            ],
        ),
        # ── Division 09 - Finishes ─────────────────────────────────────
        (
            "09",
            "Division 09 - Finishes",
            {"masterformat": "09 00 00"},
            [
                ("09.1", "Metal stud framing, suite partitions", "m2", 96000, 36.00, {"masterformat": "09 22 16"}),
                ("09.2", "Gypsum board, both faces, taped/sanded", "m2", 192000, 26.00, {"masterformat": "09 29 00"}),
                ("09.3", "STC-rated acoustic demising assembly", "m2", 28000, 68.00, {"masterformat": "09 21 00"}),
                ("09.4", "Resilient sound-control ceiling, suites", "m2", 142000, 34.00, {"masterformat": "09 29 00"}),
                ("09.5", "Acoustic tile ceiling, corridors and amenity", "m2", 22000, 46.00, {"masterformat": "09 51 00"}),
                ("09.6", "Ceramic wall tile, suite bathrooms", "m2", 18600, 86.00, {"masterformat": "09 30 00"}),
                ("09.7", "Porcelain floor tile, baths and entries", "m2", 24000, 105.00, {"masterformat": "09 30 00"}),
                ("09.8", "Engineered wide-plank flooring, suites", "m2", 96000, 78.00, {"masterformat": "09 64 00"}),
                ("09.9", "Luxury vinyl tile, amenity and BOH", "m2", 12800, 64.00, {"masterformat": "09 65 00"}),
                ("09.10", "Carpet tile, corridors", "m2", 16400, 52.00, {"masterformat": "09 68 00"}),
                ("09.11", "Polished concrete / epoxy, parking levels", "m2", 52000, 38.00, {"masterformat": "09 67 00"}),
                ("09.12", "Natural stone, lobby floor and feature walls", "m2", 1800, 285.00, {"masterformat": "09 63 40"}),
                ("09.13", "Interior painting, two coats", "m2", 218000, 11.20, {"masterformat": "09 91 00"}),
                ("09.14", "Base and trim millwork", "m", 38000, 12.50, {"masterformat": "09 64 00"}),
                ("09.15", "Acoustic wall panels, party/co-work rooms", "m2", 1400, 145.00, {"masterformat": "09 84 00"}),
                ("09.16", "Suite kitchen and vanity casework", "suite", 412, 12500.00, {"masterformat": "12 35 30"}),
                ("09.17", "Suite appliance package, ENERGY STAR", "suite", 412, 6800.00, {"masterformat": "11 31 00"}),
            ],
        ),
        # ── Division 14 - Conveying Systems (Elevators) ────────────────
        (
            "14",
            "Division 14 - Conveying Systems",
            {"masterformat": "14 00 00"},
            [
                ("14.1", "Gearless MRL passenger elevator, 1600 kg, high-rise", "pcs", 5, 425000.00, {"masterformat": "14 21 00"}),
                ("14.2", "Gearless MRL passenger elevator, 1360 kg, low-rise", "pcs", 3, 345000.00, {"masterformat": "14 21 00"}),
                ("14.3", "Service / moving elevator, 2270 kg", "pcs", 1, 465000.00, {"masterformat": "14 21 00"}),
                ("14.4", "Stainless landing entrances", "pcs", 432, 4200.00, {"masterformat": "14 28 00"}),
                ("14.5", "Destination-dispatch control and group supervisory", "lsum", 1, 185000.00, {"masterformat": "14 28 00"}),
            ],
        ),
        # ── Division 21 - Fire Suppression ─────────────────────────────
        (
            "21",
            "Division 21 - Fire Suppression",
            {"masterformat": "21 00 00"},
            [
                ("21.1", "Automatic wet sprinkler system, full building", "m2", 52800, 26.50, {"masterformat": "21 13 00"}),
                ("21.2", "Electric fire pump with jockey pump", "pcs", 1, 165000.00, {"masterformat": "21 30 00"}),
                ("21.3", "Standpipes, hose valves and fire-department connections", "m", 920, 295.00, {"masterformat": "21 12 00"}),
                ("21.4", "Portable extinguishers and hose cabinets", "pcs", 240, 480.00, {"masterformat": "21 10 00"}),
            ],
        ),
        # ── Division 22 - Plumbing ─────────────────────────────────────
        (
            "22",
            "Division 22 - Plumbing",
            {"masterformat": "22 00 00"},
            [
                ("22.1", "Sanitary and venting risers/branches, suites", "m", 9600, 76.00, {"masterformat": "22 13 00"}),
                ("22.2", "Domestic water risers and branch piping", "m", 11800, 62.00, {"masterformat": "22 11 00"}),
                ("22.3", "Storm drainage, interior", "m", 3200, 92.00, {"masterformat": "22 14 00"}),
                ("22.4", "Suite plumbing fixtures, complete", "suite", 412, 5200.00, {"masterformat": "22 40 00"}),
                ("22.5", "Amenity and common-area fixtures", "pcs", 64, 1850.00, {"masterformat": "22 40 00"}),
                ("22.6", "High-efficiency domestic hot-water plant", "lsum", 1, 285000.00, {"masterformat": "22 33 00"}),
                ("22.7", "Domestic booster pump package", "pcs", 2, 48000.00, {"masterformat": "22 11 23"}),
                ("22.8", "Duplex sump and sanitary ejector pumps", "pcs", 8, 5400.00, {"masterformat": "22 14 29"}),
                ("22.9", "Greywater / rainwater reuse cistern (TGS)", "lsum", 1, 145000.00, {"masterformat": "22 13 00"}),
                ("22.10", "Pipe insulation", "m", 14800, 18.00, {"masterformat": "22 07 00"}),
            ],
        ),
        # ── Division 23 - HVAC ─────────────────────────────────────────
        (
            "23",
            "Division 23 - Heating, Ventilation & Air Conditioning",
            {"masterformat": "23 00 00"},
            [
                ("23.1", "Suite heat-pump / fan-coil units, four-pipe", "suite", 412, 7800.00, {"masterformat": "23 82 19"}),
                ("23.2", "Make-up air units with energy recovery", "pcs", 6, 165000.00, {"masterformat": "23 73 00"}),
                ("23.3", "Air-cooled chiller plant, podium roof", "pcs", 2, 295000.00, {"masterformat": "23 64 00"}),
                ("23.4", "Condensing boiler plant, gas", "pcs", 3, 82000.00, {"masterformat": "23 52 00"}),
                ("23.5", "Corridor pressurization and stair AHUs", "pcs", 4, 58000.00, {"masterformat": "23 73 00"}),
                ("23.6", "Galvanized ductwork", "kg", 142000, 12.80, {"masterformat": "23 31 00"}),
                ("23.7", "Hydronic distribution piping, risers", "m", 9800, 95.00, {"masterformat": "23 21 00"}),
                ("23.8", "Suite bathroom and dryer exhaust", "suite", 412, 1450.00, {"masterformat": "23 34 00"}),
                ("23.9", "Diffusers, grilles and registers", "pcs", 3200, 145.00, {"masterformat": "23 37 00"}),
                ("23.10", "Fire and smoke dampers", "pcs", 680, 420.00, {"masterformat": "23 33 00"}),
                ("23.11", "Parking-garage CO/NO2 ventilation and fans", "pcs", 12, 16500.00, {"masterformat": "23 34 00"}),
                ("23.12", "Building automation system (BAS/DDC)", "lsum", 1, 685000.00, {"masterformat": "23 09 00"}),
                ("23.13", "Testing, balancing and commissioning", "lsum", 1, 285000.00, {"masterformat": "23 05 93"}),
            ],
        ),
        # ── Division 26 - Electrical ───────────────────────────────────
        (
            "26",
            "Division 26 - Electrical",
            {"masterformat": "26 00 00"},
            [
                ("26.1", "Main electrical service, 4000 A, 600 V", "lsum", 1, 485000.00, {"masterformat": "26 24 00"}),
                ("26.2", "Dry-type distribution transformers", "pcs", 8, 44000.00, {"masterformat": "26 22 00"}),
                ("26.3", "Diesel standby generator, 1000 kW, with ATS", "pcs", 1, 465000.00, {"masterformat": "26 32 13"}),
                ("26.4", "Suite panelboards and metering", "suite", 412, 3200.00, {"masterformat": "26 24 16"}),
                ("26.5", "House and amenity distribution panels", "pcs", 48, 8500.00, {"masterformat": "26 24 16"}),
                ("26.6", "Cable tray, conduit and raceway", "m", 18600, 38.00, {"masterformat": "26 05 33"}),
                ("26.7", "Branch wiring and devices, suites", "suite", 412, 9800.00, {"masterformat": "26 05 19"}),
                ("26.8", "LED luminaires, common and amenity areas", "pcs", 6800, 245.00, {"masterformat": "26 51 00"}),
                ("26.9", "Emergency and exit lighting", "pcs", 920, 245.00, {"masterformat": "26 52 00"}),
                ("26.10", "Lighting controls, common areas", "lsum", 1, 165000.00, {"masterformat": "26 09 23"}),
                ("26.11", "Grounding and bonding", "lsum", 1, 95000.00, {"masterformat": "26 05 26"}),
                ("26.12", "EV charging, Level 2 with load management (TGS)", "pcs", 160, 6500.00, {"masterformat": "26 27 00"}),
                ("26.13", "Surge protection", "pcs", 48, 1850.00, {"masterformat": "26 43 00"}),
                ("26.14", "Fire alarm and voice communication system", "lsum", 1, 485000.00, {"masterformat": "28 31 00"}),
                ("26.15", "Structured cabling, security and intercom", "lsum", 1, 385000.00, {"masterformat": "27 10 00"}),
            ],
        ),
        # ── Division 32 - Exterior Improvements (Sitework) ─────────────
        (
            "32",
            "Division 32 - Exterior Improvements",
            {"masterformat": "32 00 00"},
            [
                ("32.1", "Reinforced-concrete parking ramp and apron", "m2", 1600, 285.00, {"masterformat": "03 30 00"}),
                ("32.2", "Asphalt paving, service and laneway access", "m2", 1400, 62.00, {"masterformat": "32 12 00"}),
                ("32.3", "Concrete unit pavers, public realm and POPS", "m2", 2200, 158.00, {"masterformat": "32 14 00"}),
                ("32.4", "Concrete sidewalks and curbs", "m2", 1800, 95.00, {"masterformat": "32 16 00"}),
                ("32.5", "Soil cells and structural soil for street trees", "m3", 480, 420.00, {"masterformat": "32 94 00"}),
                ("32.6", "Trees and shrub planting, streetscape", "pcs", 120, 850.00, {"masterformat": "32 93 00"}),
                ("32.7", "Sod and landscape planting", "m2", 1600, 24.00, {"masterformat": "32 92 00"}),
                ("32.8", "Site furnishings and bike racks", "lsum", 1, 145000.00, {"masterformat": "32 33 00"}),
                ("32.9", "Stormwater retention/quality (TGS)", "lsum", 1, 285000.00, {"masterformat": "33 40 00"}),
                ("32.10", "Drip irrigation, planters and terrace", "m2", 1600, 19.00, {"masterformat": "32 84 00"}),
            ],
        ),
    ],
    markups=[
        ("General Conditions", 8.5, "overhead", "direct_cost"),
        ("Overhead & Profit", 8.0, "profit", "direct_cost"),
        ("Design and Construction Contingency", 7.5, "contingency", "direct_cost"),
        ("HST (13%)", 13.0, "tax", "direct_cost"),
    ],
    total_months=36,
    tender_name="Concrete Superstructure",
    tender_companies=[
        ("EllisDon Corporation", "bids@ellisdon.com", 0.99),
        ("PCL Constructors Canada Inc.", "estimating@pcl.com", 1.03),
        ("Deltera Inc.", "tenders@deltera.ca", 0.97),
    ],
    project_metadata={
        "address": "85 Bathurst Street, Toronto, ON M5V 0L9",
        "client": "Tridel Builders Inc.",
        "architect": "BDP Quadrangle",
        "structural_engineer": "Jablonsky, Ast and Partners",
        "general_contractor_form": "CCDC 2 (2020) - stipulated price",
        "gfa_above_grade_m2": 38600,
        "gfa_below_grade_m2": 14200,
        "storeys_tower": 45,
        "podium_storeys": 6,
        "parking_levels": 4,
        "residential_suites": 412,
        "parking_stalls": 318,
        "structure_system": "Cast-in-place RC flat-plate with shear-wall core and PT podium transfer slab",
        "envelope_system": "Window-wall (slab-edge) with insulated spandrel and operable vents",
        "cost_region": "CA_TORONTO",
        "codes": [
            "National Building Code of Canada (NBC) 2020",
            "Ontario Building Code (OBC), O. Reg. 332/12",
            "CSA A23.1/A23.3 - concrete materials and design of concrete structures",
            "CSA S16 - design of steel structures",
            "NBC 2020 seismic provisions (Toronto, Site Class D)",
        ],
        "permits": (
            "City of Toronto building permit (Toronto Building); Site Plan "
            "Approval under Section 114; TGS Version 4 Tier 1 statutory "
            "performance; MECP Excess Soil registration; TRCA review."
        ),
        "sustainability": "Toronto Green Standard Version 4, Tier 1; ENERGY STAR appliances; EV-ready",
        "seismic": "NBC 2020, Toronto region - Site Class D, SFRS reinforced-concrete shear-wall core",
        "taxes_note": (
            "HST at 13% applies in Ontario. The HST markup line is shown for "
            "illustration; position unit rates are direct costs before HST."
        ),
    },
    tender_packages=[
        (
            "Structure (Shoring + Concrete)",
            "Excavation, caisson shoring, cast-in-place concrete, post-tensioning",
            "evaluating",
            [
                ("EllisDon Corporation", "bids@ellisdon.com", 0.99),
                ("PCL Constructors Canada Inc.", "estimating@pcl.com", 1.03),
                ("Deltera Inc.", "tenders@deltera.ca", 0.97),
            ],
        ),
        (
            "Building Envelope (Window-Wall)",
            "Window-wall, curtain wall, storefront, masonry, roofing, waterproofing",
            "evaluating",
            [
                ("Sota Glazing Inc.", "estimating@sotaglazing.com", 0.98),
                ("Ferguson Neudorf Glass Inc.", "bids@fngci.com", 1.05),
                ("Antamex / Inland Glazing", "tenders@antamex.com", 1.01),
            ],
        ),
        (
            "Mechanical (HVAC + Plumbing + Fire)",
            "Suite HVAC, MAU/ERV, hydronics, plumbing risers, sprinkler/standpipe",
            "evaluating",
            [
                ("Modern Niagara Toronto Inc.", "estimating@modernniagara.com", 0.99),
                ("Black & McDonald Limited", "bids@blackandmcdonald.com", 1.04),
                ("The State Group Inc.", "tenders@stategroup.com", 1.02),
            ],
        ),
        (
            "Electrical + Life Safety",
            "Service, generator, suite power, lighting, EV charging, fire alarm, ELV",
            "evaluating",
            [
                ("Ozz Electric Inc.", "estimating@ozzelectric.com", 0.98),
                ("Plan Group Inc.", "bids@plangroup.com", 1.05),
                ("Guild Electric Limited", "tenders@guildelectric.com", 1.02),
            ],
        ),
        (
            "Interior Finishes + Fit-Out",
            "Partitions, drywall, flooring, tile, paint, suite kitchens and casework",
            "evaluating",
            [
                ("Tonda Construction", "estimating@tondaconstruction.ca", 0.97),
                ("Maystar General Contractors", "bids@maystar.ca", 1.04),
                ("Aquicon Construction Co. Ltd.", "tenders@aquicon.com", 1.01),
            ],
        ),
        (
            "Sitework and Landscape",
            "Parking ramp, paving, public realm, planting, stormwater, irrigation",
            "evaluating",
            [
                ("Aecon Group Inc.", "bids@aecon.com", 0.99),
                ("Gateman-Milloy Inc.", "estimating@gateman-milloy.com", 1.06),
            ],
        ),
    ],
    budget_boq_name="Detailed Estimate - MasterFormat 2020",
    planned_budget=228000000.0,
    actual_spend_ratio=0.42,
    spi_override=0.97,
    cpi_override=1.02,
)
