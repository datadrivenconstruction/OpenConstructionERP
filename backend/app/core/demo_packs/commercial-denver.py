# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: us-costdata  ─  Commercial Office Building, Denver, Colorado
# ---------------------------------------------------------------------------
# Class A speculative office building, LoDo / RiNo edge of Downtown Denver.
# ~12,200 m2 (131,300 sf) gross, 7 storeys + 1-level below-grade parking.
# Cast-in-place concrete podium + structural steel frame above, composite
# metal deck floors, unitised aluminium curtain wall. Core-and-shell base
# building with one floor of speculative tenant fit-out (warm shell elsewhere).
# Priced to CSI MasterFormat 2020 (5-digit), a US city cost index for Denver
# (~0.98 of US national average), base date 2026-Q1. IBC 2021 / ACI 318-19 /
# AISC 360-16 / ASCE 7-22 (Seismic Design Category B, Risk Cat II), NEC 2023,
# OSHA 29 CFR 1926. Headline base construction cost ~ USD 36.5M.
#
# NOTE on tax: Colorado state sales/use tax (2.9%) plus City & County of
# Denver tax (combined ~8.81% on taxable materials) is NOT baked into the
# unit rates below. Construction materials use tax is captured at the
# project level as a separate markup line (see markups[] and metadata).
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="commercial-denver",
    project_name="Larimer & 18th Office Building",
    project_description=(
        "New-build Class A speculative office building in the RiNo / LoDo edge "
        "of downtown Denver, Colorado. 7 storeys above grade plus one level of "
        "below-grade structured parking (62 stalls). Gross floor area approx. "
        "12,200 m2 (131,300 sf); rentable area approx. 10,400 m2. Cast-in-place "
        "concrete foundations and parking podium, structural steel frame "
        "(AISC 360-16) with composite metal-deck floors above, unitised "
        "aluminium curtain wall envelope. Core-and-shell base building with one "
        "spec tenant fit-out floor; remainder warm shell. Designed to IBC 2021, "
        "ACI 318-19, ASCE 7-22 (Seismic Design Category B, Risk Category II), "
        "NEC 2023. LEED v4 Gold target. Estimated base construction cost "
        "approx. USD 36.5M."
    ),
    region="US",
    classification_standard="masterformat",
    currency="USD",
    locale="en-US",
    address={
        "street": "1801 Larimer Street",
        "city": "Denver",
        "postcode": "CO 80202",
        "country": "United States",
        "lat": 39.7508,
        "lng": -104.9942,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Larimer & 18th - Schematic Cost Estimate (division-based)",
    # Described by category, the way the other demo packs describe themselves:
    # this string is the bill's description in the product, and a publisher's
    # name in seeded user data is the one place the classification gate cannot
    # tell demo content from a claim about our own.
    boq_description=(
        "Detailed core-and-shell + spec fit-out cost estimate to standard "
        "division numbering, Denver 2026 regional pricing, IBC 2021."
    ),
    boq_metadata={
        "standard": "Division-based work-results classification",
        "phase": "Schematic Design Estimate (Class 3, AACE)",
        "base_date": "2026-Q1",
        "price_level": "Denver, CO 2026 (regional cost index ~0.98)",
    },
    sections=[
        # -- 01 General Requirements -------------------------------------------
        (
            "01",
            "01 - General project requirements and temporary provisions",
            {"masterformat": "01"},
            [
                ("01.010", "General conditions & project management staff (General conditions)", "month", 20, 78000.00, {"masterformat": "01 31 00"}),
                ("01.020", "Field office, trailers & temporary facilities (Temporary facilities)", "lsum", 1, 285000.00, {"masterformat": "01 50 00"}),
                ("01.030", "Temporary power, water & utilities (Temporary utilities)", "month", 20, 8500.00, {"masterformat": "01 51 00"}),
                ("01.040", "Tower crane mobilize, rent & demob (Tower crane)", "month", 12, 42000.00, {"masterformat": "01 54 00"}),
                ("01.050", "OSHA 1926 safety program & fall protection (Safety program)", "lsum", 1, 165000.00, {"masterformat": "01 35 29"}),
                ("01.060", "Surveying & layout control (Survey/layout)", "lsum", 1, 95000.00, {"masterformat": "01 71 23"}),
                ("01.070", "Construction waste management & recycling (Waste mgmt)", "lsum", 1, 88000.00, {"masterformat": "01 74 19"}),
                ("01.080", "Final cleaning (Final cleaning)", "m2", 12200, 6.50, {"masterformat": "01 74 23"}),
                ("01.090", "Commissioning (Cx) authority - LEED v4 (Commissioning)", "lsum", 1, 145000.00, {"masterformat": "01 91 00"}),
            ],
        ),
        # -- 03 Concrete -------------------------------------------------------
        (
            "03",
            "03 - Cast-in-place and precast concrete work (ACI 318-19)",
            {"masterformat": "03"},
            [
                ("03.010", "Spread & continuous footings, f'c 4000 psi (Footings)", "m3", 620, 295.00, {"masterformat": "03 30 00"}),
                ("03.020", "Below-grade foundation walls 300mm (Foundation walls)", "m3", 480, 480.00, {"masterformat": "03 30 00"}),
                ("03.030", "Slab-on-grade 150mm w/ WWF & vapor barrier (Slab on grade)", "m2", 1850, 58.00, {"masterformat": "03 30 00"}),
                ("03.040", "Parking podium suspended slab 250mm (Podium slab)", "m3", 540, 425.00, {"masterformat": "03 30 00"}),
                ("03.050", "Concrete columns, podium f'c 5000 psi (Columns)", "m3", 180, 520.00, {"masterformat": "03 30 00"}),
                ("03.060", "Composite topping slab on metal deck 75mm (Topping slab)", "m2", 9800, 38.00, {"masterformat": "03 30 00"}),
                ("03.070", "Formwork, all cast-in-place elements (Formwork)", "m2", 11200, 62.00, {"masterformat": "03 11 00"}),
                ("03.080", "Reinforcing steel #4-#9, ASTM A615 Gr60 (Rebar)", "t", 410, 2450.00, {"masterformat": "03 21 00"}),
                ("03.090", "Concrete pumping & placement (Place & finish)", "m3", 1820, 48.00, {"masterformat": "03 31 00"}),
                ("03.100", "Sealed/polished concrete floor finish (Polished slab)", "m2", 1850, 24.00, {"masterformat": "03 35 43"}),
            ],
        ),
        # -- 04 Masonry --------------------------------------------------------
        (
            "04",
            "04 - Brick, block and stone work",
            {"masterformat": "04"},
            [
                ("04.010", "CMU 200mm load-bearing, stair/elevator cores (CMU walls)", "m2", 2400, 115.00, {"masterformat": "04 22 00"}),
                ("04.020", "CMU 200mm fire-rated shaft walls (Shaft walls)", "m2", 1200, 128.00, {"masterformat": "04 22 00"}),
                ("04.030", "Brick veneer at street-level base (Brick veneer)", "m2", 850, 235.00, {"masterformat": "04 21 13"}),
                ("04.040", "Cast stone trim & sills (Cast stone)", "m", 320, 165.00, {"masterformat": "04 72 00"}),
                ("04.050", "Masonry reinforcing, ties & grout (Reinf & grout)", "lsum", 1, 78000.00, {"masterformat": "04 05 16"}),
            ],
        ),
        # -- 05 Metals (AISC 360-16) -------------------------------------------
        (
            "05",
            "05 - Structural and miscellaneous metal work (AISC 360-16)",
            {"masterformat": "05"},
            [
                ("05.010", "Structural steel frame, W-shapes ASTM A992 (Steel frame)", "t", 720, 4250.00, {"masterformat": "05 12 00"}),
                ("05.020", "Steel deck, composite 3in 20ga galvanized (Metal deck)", "m2", 9800, 52.00, {"masterformat": "05 31 00"}),
                ("05.030", "Roof deck, type B 1.5in 22ga (Roof deck)", "m2", 1900, 42.00, {"masterformat": "05 31 00"}),
                ("05.040", "Shear studs, headed 19mm welded (Shear connectors)", "pcs", 18500, 3.20, {"masterformat": "05 12 00"}),
                ("05.050", "Steel stairs, pan-filled w/ railings (Egress stairs)", "pcs", 14, 28500.00, {"masterformat": "05 51 00"}),
                ("05.060", "Miscellaneous metals, embeds & lintels (Misc metals)", "t", 38, 5800.00, {"masterformat": "05 50 00"}),
                ("05.070", "Galvanized steel pipe railings, roof/mech (Pipe railings)", "m", 420, 145.00, {"masterformat": "05 52 13"}),
                ("05.080", "Structural steel fireproofing (SFRM 2hr) (Fireproofing)", "m2", 9800, 18.50, {"masterformat": "07 81 00"}),
            ],
        ),
        # -- 06 Wood, Plastics & Composites ------------------------------------
        (
            "06",
            "06 - Carpentry, millwork and composite framing",
            {"masterformat": "06"},
            [
                ("06.010", "Rough carpentry, blocking & nailers (Rough carpentry)", "lsum", 1, 68000.00, {"masterformat": "06 10 00"}),
                ("06.020", "Plastic-laminate millwork, lobby reception (Millwork)", "m", 65, 980.00, {"masterformat": "06 41 00"}),
                ("06.030", "Architectural wood paneling, lobby feature wall (Wood paneling)", "m2", 280, 425.00, {"masterformat": "06 42 00"}),
                ("06.040", "Solid-surface countertops, break rooms (Countertops)", "m2", 120, 520.00, {"masterformat": "06 61 00"}),
            ],
        ),
        # -- 07 Thermal & Moisture Protection ----------------------------------
        (
            "07",
            "07 - Roofing, waterproofing and insulation",
            {"masterformat": "07"},
            [
                ("07.010", "Below-grade waterproofing, sheet membrane (Waterproofing)", "m2", 2600, 52.00, {"masterformat": "07 13 00"}),
                ("07.020", "Foundation drainage & protection board (Drainage board)", "m2", 1800, 22.00, {"masterformat": "07 10 00"}),
                ("07.030", "Spray polyurethane foam air/insulation, walls (SPF insulation)", "m2", 4200, 38.00, {"masterformat": "07 21 00"}),
                ("07.040", "Roof insulation, polyiso R-30 tapered (Roof insulation)", "m2", 1900, 42.00, {"masterformat": "07 22 00"}),
                ("07.050", "TPO single-ply roof membrane, mechanically fastened (TPO roof)", "m2", 1900, 78.00, {"masterformat": "07 54 23"}),
                ("07.060", "Sheet-metal flashing, copings & trim (Flashing)", "m", 480, 95.00, {"masterformat": "07 62 00"}),
                ("07.070", "Roof drains, overflow & scuppers (Roof drainage)", "pcs", 18, 1850.00, {"masterformat": "07 71 00"}),
                ("07.080", "Firestopping & fire-rated joint systems (Firestopping)", "lsum", 1, 125000.00, {"masterformat": "07 84 00"}),
                ("07.090", "Joint sealants, exterior & interior (Sealants)", "lsum", 1, 88000.00, {"masterformat": "07 92 00"}),
            ],
        ),
        # -- 08 Openings -------------------------------------------------------
        (
            "08",
            "08 - Doors, windows and glazed assemblies",
            {"masterformat": "08"},
            [
                ("08.010", "Unitised aluminium curtain wall, thermally broken (Curtain wall)", "m2", 5600, 685.00, {"masterformat": "08 44 13"}),
                ("08.020", "Storefront glazing, ground-floor retail (Storefront)", "m2", 620, 540.00, {"masterformat": "08 43 13"}),
                ("08.030", "Insulating low-E glazing units, vision (IGU vision glass)", "m2", 4200, 165.00, {"masterformat": "08 80 00"}),
                ("08.040", "Spandrel glass & shadow-box panels (Spandrel)", "m2", 1400, 145.00, {"masterformat": "08 80 00"}),
                ("08.050", "Hollow-metal doors & frames, fire-rated (HM doors)", "pcs", 95, 1450.00, {"masterformat": "08 11 13"}),
                ("08.060", "Interior wood doors, solid-core, prefinished (Wood doors)", "pcs", 130, 850.00, {"masterformat": "08 14 16"}),
                ("08.070", "Automatic sliding entrance doors, lobby (Auto entrance)", "pcs", 4, 22500.00, {"masterformat": "08 42 29"}),
                ("08.080", "Overhead coiling doors, loading/parking (Coiling doors)", "pcs", 3, 8500.00, {"masterformat": "08 33 23"}),
                ("08.090", "Door hardware, ANSI/BHMA Grade 1 (Door hardware)", "pcs", 225, 685.00, {"masterformat": "08 71 00"}),
            ],
        ),
        # -- 09 Finishes -------------------------------------------------------
        (
            "09",
            "09 - Interior finishing: drywall, flooring, painting",
            {"masterformat": "09"},
            [
                ("09.010", "Metal-stud & gypsum board partitions (GWB partitions)", "m2", 14500, 62.00, {"masterformat": "09 21 16"}),
                ("09.020", "Shaft-wall & fire-rated assemblies (Shaft wall)", "m2", 2200, 88.00, {"masterformat": "09 21 16"}),
                ("09.030", "Suspended acoustic ceiling tile 600x600 (ACT ceiling)", "m2", 6200, 48.00, {"masterformat": "09 51 13"}),
                ("09.040", "Gypsum board ceilings & soffits (GWB ceilings)", "m2", 1800, 58.00, {"masterformat": "09 29 00"}),
                ("09.050", "Porcelain tile, lobby & restrooms (Tile)", "m2", 1650, 145.00, {"masterformat": "09 30 13"}),
                ("09.060", "Carpet tile, modular, tenant areas (Carpet tile)", "m2", 5400, 58.00, {"masterformat": "09 68 13"}),
                ("09.070", "Luxury vinyl tile (LVT), circulation (LVT)", "m2", 2200, 65.00, {"masterformat": "09 65 19"}),
                ("09.080", "Terrazzo flooring, main lobby (Terrazzo)", "m2", 420, 285.00, {"masterformat": "09 66 13"}),
                ("09.090", "Painting & wall coatings, interior (Paint)", "m2", 22000, 14.50, {"masterformat": "09 91 23"}),
                ("09.100", "High-performance exterior coatings (Ext coatings)", "m2", 1800, 32.00, {"masterformat": "09 96 00"}),
            ],
        ),
        # -- 10 Specialties ----------------------------------------------------
        (
            "10",
            "10 - Built-in specialty items and signage",
            {"masterformat": "10"},
            [
                ("10.010", "Toilet partitions, solid phenolic (Toilet partitions)", "pcs", 64, 1250.00, {"masterformat": "10 21 13"}),
                ("10.020", "Toilet & bath accessories (Washroom accessories)", "pcs", 14, 4800.00, {"masterformat": "10 28 00"}),
                ("10.030", "Building signage & code wayfinding (Signage)", "lsum", 1, 95000.00, {"masterformat": "10 14 00"}),
                ("10.040", "Fire extinguishers & cabinets (Fire extinguishers)", "pcs", 48, 425.00, {"masterformat": "10 44 00"}),
                ("10.050", "Lockers & bicycle storage room fit-out (Lockers/bike)", "lsum", 1, 68000.00, {"masterformat": "10 51 00"}),
                ("10.060", "Operable partitions, conference (Operable partitions)", "m2", 90, 850.00, {"masterformat": "10 22 26"}),
            ],
        ),
        # -- 14 Conveying Equipment --------------------------------------------
        (
            "14",
            "14 - Elevators, escalators and lifts",
            {"masterformat": "14"},
            [
                ("14.010", "Passenger elevators, MRL gearless 1600kg/7-stop (Passenger lifts)", "pcs", 3, 215000.00, {"masterformat": "14 21 00"}),
                ("14.020", "Service elevator, 2000kg (Service lift)", "pcs", 1, 245000.00, {"masterformat": "14 21 00"}),
                ("14.030", "Elevator shaft pressurization & controls (Lift controls)", "lsum", 1, 85000.00, {"masterformat": "14 28 00"}),
            ],
        ),
        # -- 21 Fire Suppression -----------------------------------------------
        (
            "21",
            "21 - Sprinkler and fire-suppression systems (NFPA 13)",
            {"masterformat": "21"},
            [
                ("21.010", "Wet-pipe sprinkler system, full coverage (Sprinklers)", "m2", 12200, 34.00, {"masterformat": "21 13 13"}),
                ("21.020", "Fire pump assembly, electric 1000 gpm (Fire pump)", "pcs", 1, 125000.00, {"masterformat": "21 30 00"}),
                ("21.030", "Standpipe system, Class I egress stairs (Standpipe)", "lsum", 1, 95000.00, {"masterformat": "21 12 00"}),
                ("21.040", "Clean-agent suppression, IT/MDF rooms (Clean agent)", "pcs", 4, 38000.00, {"masterformat": "21 22 00"}),
            ],
        ),
        # -- 22 Plumbing -------------------------------------------------------
        (
            "22",
            "22 - Piping systems and sanitary fixtures",
            {"masterformat": "22"},
            [
                ("22.010", "Domestic water distribution, copper/PEX (Domestic water)", "m2", 12200, 28.00, {"masterformat": "22 11 00"}),
                ("22.020", "Sanitary & vent waste piping (Sanitary drainage)", "m2", 12200, 24.00, {"masterformat": "22 13 00"}),
                ("22.030", "Storm drainage piping, interior (Storm drainage)", "m", 680, 95.00, {"masterformat": "22 14 00"}),
                ("22.040", "Plumbing fixtures, low-flow WaterSense (Fixtures)", "pcs", 145, 1450.00, {"masterformat": "22 40 00"}),
                ("22.050", "Domestic hot-water plant, gas water heaters (DHW plant)", "pcs", 4, 18500.00, {"masterformat": "22 33 00"}),
                ("22.060", "Natural gas distribution & meters (Gas piping)", "lsum", 1, 88000.00, {"masterformat": "22 11 23"}),
            ],
        ),
        # -- 23 HVAC -----------------------------------------------------------
        (
            "23",
            "23 - Heating, cooling and ventilation systems",
            {"masterformat": "23"},
            [
                ("23.010", "Rooftop VAV air-handling units, 100% OA economizer (RTU/AHU)", "pcs", 6, 165000.00, {"masterformat": "23 74 13"}),
                ("23.020", "Sheet-metal supply/return ductwork (Ductwork)", "kg", 95000, 12.50, {"masterformat": "23 31 13"}),
                ("23.030", "VAV terminal units w/ reheat (VAV boxes)", "pcs", 185, 1850.00, {"masterformat": "23 36 00"}),
                ("23.040", "Hydronic piping, heating hot water (Hydronic piping)", "m", 2400, 95.00, {"masterformat": "23 21 13"}),
                ("23.050", "Gas-fired condensing boilers, 1500 MBH (Boilers)", "pcs", 2, 78000.00, {"masterformat": "23 52 00"}),
                ("23.060", "Air-cooled chiller, 300 ton (Chiller)", "pcs", 1, 285000.00, {"masterformat": "23 64 23"}),
                ("23.070", "Pumps, VFD-driven primary/secondary (Pumps)", "pcs", 8, 12500.00, {"masterformat": "23 21 23"}),
                ("23.080", "Pipe & duct insulation (HVAC insulation)", "m2", 6500, 28.00, {"masterformat": "23 07 00"}),
                ("23.090", "Testing, adjusting & balancing (TAB)", "lsum", 1, 145000.00, {"masterformat": "23 05 93"}),
                ("23.100", "Building automation system, DDC (BAS/DDC)", "m2", 12200, 24.00, {"masterformat": "23 09 23"}),
            ],
        ),
        # -- 26 Electrical (NEC 2023) ------------------------------------------
        (
            "26",
            "26 - Power distribution and lighting systems (NEC 2023)",
            {"masterformat": "26"},
            [
                ("26.010", "Utility service, 2500A 480/277V switchgear (Service/switchgear)", "lsum", 1, 485000.00, {"masterformat": "26 24 13"}),
                ("26.020", "Panelboards, transformers & distribution (Distribution)", "lsum", 1, 625000.00, {"masterformat": "26 24 16"}),
                ("26.030", "Branch wiring, conduit & devices (Branch wiring)", "m2", 12200, 78.00, {"masterformat": "26 05 19"}),
                ("26.040", "Interior LED lighting & controls, DLC (LED lighting)", "m2", 12200, 62.00, {"masterformat": "26 51 13"}),
                ("26.050", "Exterior & site LED lighting (Site lighting)", "pcs", 42, 1850.00, {"masterformat": "26 56 00"}),
                ("26.060", "Emergency/standby diesel generator, 600kW (Generator)", "pcs", 1, 345000.00, {"masterformat": "26 32 13"}),
                ("26.070", "Automatic transfer switch & emergency dist (ATS/emergency)", "lsum", 1, 165000.00, {"masterformat": "26 36 00"}),
                ("26.080", "Grounding, bonding & lightning protection (Grounding)", "lsum", 1, 95000.00, {"masterformat": "26 05 26"}),
                ("26.090", "EV charging stations, Level 2 (EV charging)", "pcs", 10, 8500.00, {"masterformat": "26 56 36"}),
            ],
        ),
        # -- 27 Communications -------------------------------------------------
        (
            "27",
            "27 - Voice, data and network cabling",
            {"masterformat": "27"},
            [
                ("27.010", "Structured cabling, Cat 6A backbone & horizontal (Structured cabling)", "m2", 12200, 22.00, {"masterformat": "27 10 00"}),
                ("27.020", "Telecom/IT room build-out, MDF/IDF (Telecom rooms)", "pcs", 8, 28500.00, {"masterformat": "27 11 00"}),
                ("27.030", "Distributed antenna system (DAS), public safety (DAS/ERRCS)", "lsum", 1, 185000.00, {"masterformat": "27 53 00"}),
                ("27.040", "Access control & CCTV security system (Security/access)", "m2", 12200, 14.00, {"masterformat": "28 00 00"}),
                ("27.050", "Fire alarm & mass-notification, addressable (Fire alarm)", "m2", 12200, 16.50, {"masterformat": "28 31 00"}),
            ],
        ),
        # -- 31 Earthwork ------------------------------------------------------
        (
            "31",
            "31 - Excavation, grading and earth support",
            {"masterformat": "31"},
            [
                ("31.010", "Clearing, grubbing & demolition of existing (Site clearing)", "m2", 4200, 12.00, {"masterformat": "31 10 00"}),
                ("31.020", "Mass excavation, below-grade parking (Mass excavation)", "m3", 18500, 24.00, {"masterformat": "31 23 16"}),
                ("31.030", "Excavated soil haul-off & disposal (Soil disposal)", "m3", 16000, 18.50, {"masterformat": "31 23 23"}),
                ("31.040", "Shoring & lagging, soldier pile (Shoring)", "m2", 2400, 145.00, {"masterformat": "31 50 00"}),
                ("31.050", "Dewatering & groundwater control (Dewatering)", "lsum", 1, 165000.00, {"masterformat": "31 23 19"}),
                ("31.060", "Structural fill, place & compact (Structural fill)", "m3", 3800, 32.00, {"masterformat": "31 23 23"}),
                ("31.070", "Geotechnical testing & special inspection (Geotech/SI)", "lsum", 1, 88000.00, {"masterformat": "31 09 00"}),
            ],
        ),
        # -- 32 Exterior Improvements ------------------------------------------
        (
            "32",
            "32 - Paving, landscaping and site amenities",
            {"masterformat": "32"},
            [
                ("32.010", "Asphalt paving, service drive (Asphalt paving)", "m2", 1200, 58.00, {"masterformat": "32 12 16"}),
                ("32.020", "Concrete sidewalks & ADA curb ramps (Concrete flatwork)", "m2", 1850, 78.00, {"masterformat": "32 13 13"}),
                ("32.030", "Plaza pavers on pedestals, public realm (Pavers)", "m2", 950, 165.00, {"masterformat": "32 14 13"}),
                ("32.040", "Site furnishings, benches & bike racks (Site furnishings)", "lsum", 1, 78000.00, {"masterformat": "32 33 00"}),
                ("32.050", "Landscape planting, xeriscape (Planting)", "m2", 1600, 42.00, {"masterformat": "32 93 00"}),
                ("32.060", "Drip irrigation system, water-efficient (Irrigation)", "m2", 1600, 18.00, {"masterformat": "32 84 00"}),
                ("32.070", "Storm-water detention & green infrastructure (Stormwater/GI)", "lsum", 1, 185000.00, {"masterformat": "33 40 00"}),
            ],
        ),
    ],
    markups=[
        ("General Conditions", 7.0, "overhead", "direct_cost"),
        ("Contractor Overhead & Profit", 6.0, "profit", "direct_cost"),
        ("Bond & Insurance (P&P bond + builder's risk)", 2.0, "insurance", "direct_cost"),
        ("Design Contingency", 8.0, "contingency", "direct_cost"),
        ("Colorado/Denver Construction Use Tax", 4.5, "tax", "cumulative"),
    ],
    total_months=20,
    tender_name="Core & Shell (Concrete + Steel)",
    tender_companies=[
        ("Halbridge Construction", "bids@halbridge.example", 0.98),
        ("Corvanth Construction", "preconstruction@corvanth.example", 1.03),
        ("RK Tavershaw Construction", "estimating@tavershaw.example", 1.01),
    ],
    project_metadata={
        "client": "Fenner Row Capital Partners LLC",
        "architect": "Tallowbrook Architects",
        "structural_engineer": "Ravenhurst Structural Inc.",
        "mep_engineer": "Nyland Reeve Consulting Engineers",
        "general_contractor": "Halbridge Construction (CMAR delivery)",
        "delivery_method": "Construction Manager at Risk (CMAR), AIA A201-2017",
        "gfa_m2": 12200,
        "gfa_sf": 131300,
        "rentable_m2": 10400,
        "storeys_above_grade": 7,
        "below_grade_levels": 1,
        "parking_stalls": 62,
        "structure_system": "Cast-in-place concrete podium + structural steel frame, composite metal deck",
        "building_codes": ["IBC 2021", "ACI 318-19", "AISC 360-16", "ASCE 7-22", "NEC 2023", "OSHA 29 CFR 1926"],
        "seismic": "Seismic Design Category B, Risk Category II (ASCE 7-22)",
        "sustainability": "LEED v4 Gold target; WaterSense fixtures; DLC LED lighting; EV-ready",
        "permit_authority": "City & County of Denver, Community Planning & Development (Building permit)",
        "sales_tax_note": (
            "Colorado state use tax 2.9% + City & County of Denver combined ~8.81% applies to "
            "construction materials; captured as a separate use-tax markup line, NOT in unit rates."
        ),
        "price_basis": "US city cost index for Denver (~0.98 of national average), base date 2026-Q1",
        "estimate_class": "AACE Class 3 (Schematic Design, -10%/+20%)",
    },
    tender_packages=[
        (
            "Core & Shell (Concrete + Steel)",
            "Earthwork, shoring, foundations, concrete podium, structural steel frame & deck",
            "evaluating",
            [
                ("Halbridge Construction", "bids@halbridge.example", 0.98),
                ("Corvanth Construction", "preconstruction@corvanth.example", 1.03),
                ("RK Tavershaw Construction", "estimating@tavershaw.example", 1.01),
            ],
        ),
        (
            "Building Envelope (Curtain Wall & Roofing)",
            "Unitised curtain wall, storefront, glazing, TPO roofing, waterproofing",
            "evaluating",
            [
                ("Quenmar Inc.", "bids@quenmar.example", 0.97),
                ("Sillgate Corp.", "estimating@sillgate.example", 1.05),
                ("Aspenmar Glass & Curtainwall", "tenders@aspenmar.example", 1.02),
            ],
        ),
        (
            "MEP Services (HVAC / Plumbing / Electrical / FP)",
            "HVAC, plumbing, fire suppression, electrical, low-voltage and controls",
            "evaluating",
            [
                ("Vandermill Mechanical", "estimating@vandermill.example", 0.99),
                ("Brightstake Electric", "bids@brightstake.example", 1.04),
                ("Wexhall Engineering Company", "preconstruction@wexhall.example", 1.02),
            ],
        ),
        (
            "Interior Finishes & Tenant Fit-Out",
            "Drywall, ceilings, flooring, painting, doors/hardware, millwork, specialties",
            "collecting",
            [
                ("KP Larriman Construction", "bids@larriman.example", 0.98),
                ("Thornebay Builders", "preconstruction@thornebay.example", 1.04),
                ("Ashvane Constructors", "estimating@ashvane.example", 1.01),
            ],
        ),
    ],
    schedule_activities=[
        ("Mobilization & Site Clearing", "2026-03-02", "2026-04-15"),
        ("Mass Excavation & Shoring", "2026-04-01", "2026-06-30"),
        ("Foundations & Below-Grade Walls", "2026-06-01", "2026-08-31"),
        ("Concrete Parking Podium", "2026-08-01", "2026-10-31"),
        ("Structural Steel Erection", "2026-10-01", "2027-02-28"),
        ("Metal Deck & Composite Slabs", "2026-11-01", "2027-03-31"),
        ("Building Envelope / Curtain Wall", "2027-02-01", "2027-07-31"),
        ("Roofing & Waterproofing", "2027-04-01", "2027-06-30"),
        ("MEP Rough-In", "2027-03-01", "2027-09-30"),
        ("Interior Partitions & Drywall", "2027-06-01", "2027-10-31"),
        ("Elevator Installation", "2027-06-01", "2027-09-30"),
        ("Fire Protection & Life Safety", "2027-05-01", "2027-10-31"),
        ("Interior Finishes & Fit-Out", "2027-08-01", "2027-12-31"),
        ("Commissioning & TAB", "2027-11-01", "2028-01-31"),
        ("Substantial Completion & Turnover", "2027-12-01", "2028-02-28"),
    ],
    budget_boq_name="Larimer & 18th - Control Budget",
    planned_budget=36_500_000,
    actual_spend_ratio=0.31,
    spi_override=1.01,
    cpi_override=0.97,
)
