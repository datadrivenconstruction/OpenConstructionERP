# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Flagship demo: Commercial / light-industrial building, Auckland (New Zealand)
# ---------------------------------------------------------------------------
# Elemental cost plan per NRM 1 conventions as used by NZ quantity surveyors
# (NZIQS practice). Building consent under the New Zealand Building Code (NZBC);
# structure designed to NZS 3404 (steel), NZS 3101 (concrete), NZS 1170 / NZS
# 1170.5 (structural design actions / earthquake), with light-framed elements
# to NZS 3604. Construction contract NZS 3910:2023. All rates are NZD, GST
# exclusive, at Auckland Q1 2026 price level. GST (15%) is carried as a
# separate cumulative markup, never baked into the unit rates.
#
# Program: 6,800 m2 GFA two-storey commercial / light-industrial building -
# ground-floor warehouse + showroom with first-floor office fitout. Structural
# steel portal / moment frame on a reinforced-concrete substructure, precast
# concrete tilt-up perimeter panels, long-run metal roof. Importance Level 2,
# seismic zone Auckland (low seismicity, Z=0.13), wind region A7. Headline
# construction cost circa NZD 26 million (GST exclusive).

TEMPLATE = DemoTemplate(
    demo_id="commercial-auckland",
    project_name="Highbrook Commercial Centre",
    project_description=(
        "New two-storey commercial / light-industrial building at Highbrook "
        "Business Park, East Tamaki, Auckland. Ground-floor warehouse and "
        "showroom (clear height 9.0 m) with a first-floor corporate office "
        "fitout. GFA approx. 6,800 m2 on a 1.1 ha site. Structural steel "
        "portal and moment-resisting frame (NZS 3404) on reinforced-concrete "
        "pad and strip footings with a ground-bearing slab (NZS 3101); "
        "precast tilt-up concrete perimeter panels; long-run pre-painted steel roof. "
        "Importance Level 2, seismic hazard Z=0.13 (Auckland), wind region "
        "A7, designed to NZS 1170 / NZS 1170.5. NZBC compliant, Green Star 5 "
        "Star target. Estimated construction cost circa NZD 26M (GST excl.)."
    ),
    region="NZ",
    classification_standard="nrm",
    currency="NZD",
    locale="en-NZ",
    address={
        "street": "12 Highbrook Drive, East Tamaki",
        "city": "Auckland",
        "postcode": "2013",
        "country": "New Zealand",
        "lat": -36.9456,
        "lng": 174.9089,
    },
    validation_rule_sets=["nrm", "boq_quality"],
    boq_name="Elemental Cost Plan - NRM 1 (NZ)",
    boq_description=(
        "Elemental cost plan to NRM 1 conventions (NZIQS practice), measured "
        "trades; NZ Building Code compliant, NZS 3910:2023 contract"
    ),
    boq_metadata={
        "standard": "NRM 1 (elemental) / NZS 4202 measurement",
        "phase": "Developed Design Cost Plan",
        "base_date": "2026-Q1",
        "price_level": "Auckland 2026 (NZD, GST excl.)",
    },
    sections=[
        # -- 1. Preliminaries & General -------------------------------------
        (
            "1",
            "1 - Preliminaries & General (P&G)",
            {"nrm": "0"},
            [
                ("1.1", "Site establishment and disestablishment (Site set-up)", "lsum", 1, 185000.00, {"nrm": "0.1"}),
                ("1.2", "Site office, amenities and ablutions (Site offices)", "month", 16, 6500.00, {"nrm": "0.1"}),
                ("1.3", "Site management and supervision (Staffing)", "month", 16, 42000.00, {"nrm": "0.1"}),
                ("1.4", "Temporary fencing and hoarding (Site security fencing)", "m", 420, 48.00, {"nrm": "0.1"}),
                ("1.5", "Tower / mobile crane and hoists (Cranage)", "month", 10, 28000.00, {"nrm": "0.1"}),
                ("1.6", "Temporary power, water and telecom (Temporary services)", "month", 16, 4800.00, {"nrm": "0.1"}),
                ("1.7", "Scaffolding and edge protection (Scaffold / fall arrest)", "m2", 3200, 38.00, {"nrm": "0.1"}),
                ("1.8", "Health, safety and traffic management plan (H&S / TMP)", "lsum", 1, 145000.00, {"nrm": "0.1"}),
                ("1.9", "Resource consent and building consent fees (Consent fees)", "lsum", 1, 165000.00, {"nrm": "0.1"}),
                ("1.10", "Surveying and set-out (Setting out)", "lsum", 1, 38000.00, {"nrm": "0.1"}),
                ("1.11", "Quality assurance and as-built documentation (QA / as-builts)", "lsum", 1, 52000.00, {"nrm": "0.1"}),
                ("1.12", "Final clean and progressive site cleaning (Cleaning)", "lsum", 1, 46000.00, {"nrm": "0.1"}),
            ],
        ),
        # -- 2. Site Preparation & Earthworks -------------------------------
        (
            "2",
            "2 - Site Preparation & Earthworks",
            {"nrm": "0"},
            [
                ("2.1", "Geotechnical investigation and report (Ground investigation)", "lsum", 1, 42000.00, {"nrm": "0.3"}),
                ("2.2", "Site clearance and topsoil strip (Clearing / strip)", "m2", 11000, 6.50, {"nrm": "0.1"}),
                ("2.3", "Bulk earthworks cut and fill (Bulk earthworks)", "m3", 14000, 18.50, {"nrm": "0.2"}),
                ("2.4", "Cart soft / contaminated spoil to disposal (Spoil cartage)", "m3", 5200, 38.00, {"nrm": "0.2"}),
                ("2.5", "Import and compact engineered hardfill (GAP65 fill)", "m3", 4800, 62.00, {"nrm": "0.2"}),
                ("2.6", "Erosion and sediment control (ESC measures)", "lsum", 1, 58000.00, {"nrm": "0.1"}),
                ("2.7", "Dewatering and groundwater control (Dewatering)", "lsum", 1, 36000.00, {"nrm": "0.2"}),
                ("2.8", "Sub-grade trim and proof roll to platform (Subgrade prep)", "m2", 6900, 7.20, {"nrm": "0.2"}),
            ],
        ),
        # -- 3. Substructure ------------------------------------------------
        (
            "3",
            "3 - Substructure (NZS 3101 / NZS 1170)",
            {"nrm": "1"},
            [
                ("3.1", "Mass excavation to foundations (Foundation excavation)", "m3", 2400, 24.00, {"nrm": "1.1"}),
                ("3.2", "RC pad footings to portal columns (Pad footings)", "m3", 480, 365.00, {"nrm": "1.1"}),
                ("3.3", "RC strip footings to perimeter (Strip footings)", "m3", 220, 345.00, {"nrm": "1.1"}),
                ("3.4", "Reinforcing steel Grade 500E to footings (Rebar)", "t", 78, 3450.00, {"nrm": "1.1"}),
                ("3.5", "Holding-down bolt assemblies cast-in (HD bolts)", "pcs", 96, 420.00, {"nrm": "1.1"}),
                ("3.6", "Ground-bearing slab 200mm SOG (Warehouse slab)", "m2", 4200, 145.00, {"nrm": "1.2"}),
                ("3.7", "Suspended RC slab to office on metal deck (Suspended slab)", "m2", 2600, 215.00, {"nrm": "1.2"}),
                ("3.8", "DPM / vapour barrier under slab (Damp-proof membrane)", "m2", 4200, 9.50, {"nrm": "1.2"}),
                ("3.9", "Sub-slab insulation XPS to office (Slab insulation)", "m2", 2600, 28.00, {"nrm": "1.2"}),
                ("3.10", "Termite and pest barrier system (Pest barrier)", "m2", 4200, 6.80, {"nrm": "1.1"}),
            ],
        ),
        # -- 4. Structural Frame --------------------------------------------
        (
            "4",
            "4 - Frame (NZS 3404 steel)",
            {"nrm": "2"},
            [
                ("4.1", "Structural steel portal frames fabricated (Portal frames)", "t", 320, 5650.00, {"nrm": "2.1"}),
                ("4.2", "Moment-frame columns and beams to office (MRF steelwork)", "t", 165, 5950.00, {"nrm": "2.1"}),
                ("4.3", "Eaves, ridge and roof purlins / girts (Secondary steel)", "t", 95, 4850.00, {"nrm": "2.2"}),
                ("4.4", "Cross-bracing and tension rods seismic (Seismic bracing)", "t", 42, 6200.00, {"nrm": "2.1"}),
                ("4.5", "Erect and bolt structural steel (Steel erection)", "t", 622, 1250.00, {"nrm": "2.1"}),
                ("4.6", "Hot-dip galvanising to exposed steel (Galvanising)", "t", 137, 980.00, {"nrm": "2.2"}),
                ("4.7", "Intumescent fire protection coating (Fire rating to steel)", "m2", 5800, 46.00, {"nrm": "2.1"}),
                ("4.8", "Composite metal floor deck ComFlor 80 (Floor decking)", "m2", 2600, 58.00, {"nrm": "2.3"}),
                ("4.9", "Shear studs to composite beams (Shear connectors)", "pcs", 3200, 8.50, {"nrm": "2.3"}),
            ],
        ),
        # -- 5. Upper Floors, Stairs & Roof Structure -----------------------
        (
            "5",
            "5 - Upper Floors, Stairs & Roof Structure",
            {"nrm": "2"},
            [
                ("5.1", "Steel stairs and landings to office (Internal stairs)", "pcs", 3, 28500.00, {"nrm": "2.4"}),
                ("5.2", "External fire-escape stair galvanised (Fire stair)", "pcs", 2, 34000.00, {"nrm": "2.4"}),
                ("5.3", "Stair and landing balustrades stainless (Balustrades)", "m", 140, 320.00, {"nrm": "2.4"}),
                ("5.4", "Mezzanine edge protection and handrail (Edge handrail)", "m", 210, 185.00, {"nrm": "2.4"}),
                ("5.5", "Roof structural framing long-span (Roof framing)", "t", 58, 5350.00, {"nrm": "2.5"}),
                ("5.6", "Plant deck and screen support steel (Plant deck)", "m2", 320, 195.00, {"nrm": "2.5"}),
                ("5.7", "Roof access ladder and hatch (Roof access)", "pcs", 3, 4800.00, {"nrm": "2.4"}),
            ],
        ),
        # -- 6. External Envelope -------------------------------------------
        (
            "6",
            "6 - Envelope (External Walls, Cladding, Roof)",
            {"nrm": "5"},
            [
                ("6.1", "Precast tilt-up concrete panels 180mm (Tilt panels)", "m2", 3400, 295.00, {"nrm": "5.1"}),
                ("6.2", "Panel craneage, propping and grout (Panel erection)", "m2", 3400, 78.00, {"nrm": "5.1"}),
                ("6.3", "Insulated wall panel to showroom (Insulated panel)", "m2", 1100, 235.00, {"nrm": "5.1"}),
                ("6.4", "Long-run pre-painted steel roofing 0.55 BMT (Metal roofing)", "m2", 4400, 88.00, {"nrm": "4.1"}),
                ("6.5", "Roof insulation R3.6 blanket and safety mesh (Roof insulation)", "m2", 4400, 32.00, {"nrm": "4.2"}),
                ("6.6", "Roof flashings, ridge and barge (Flashings)", "m", 720, 58.00, {"nrm": "4.1"}),
                ("6.7", "Internal rainwater spouting and downpipes (Rainwater goods)", "m", 540, 72.00, {"nrm": "4.1"}),
                ("6.8", "Aluminium curtain wall to office facade (Curtain wall)", "m2", 980, 685.00, {"nrm": "5.2"}),
                ("6.9", "Aluminium thermally broken windows IGU (Windows)", "m2", 620, 545.00, {"nrm": "5.5"}),
                ("6.10", "Powder-coated wall cladding to entry (Feature cladding)", "m2", 380, 320.00, {"nrm": "5.1"}),
                ("6.11", "Wall and roof weatherproofing membrane (Weather membrane)", "m2", 4800, 24.00, {"nrm": "5.1"}),
            ],
        ),
        # -- 7. External Doors & Glazing ------------------------------------
        (
            "7",
            "7 - External Doors, Windows & Louvres",
            {"nrm": "6"},
            [
                ("7.1", "Glazed automatic entrance doors (Auto entrance)", "pcs", 2, 24500.00, {"nrm": "6.1"}),
                ("7.2", "Industrial sectional roller doors (Roller doors)", "pcs", 6, 12800.00, {"nrm": "6.2"}),
                ("7.3", "Dock leveller loading bays (Dock levellers)", "pcs", 4, 28500.00, {"nrm": "6.2"}),
                ("7.4", "Personnel and fire-rated external doors (External doors)", "pcs", 14, 2650.00, {"nrm": "6.3"}),
                ("7.5", "External aluminium louvre screens (Plant louvres)", "m2", 145, 420.00, {"nrm": "6.1"}),
            ],
        ),
        # -- 8. Internal Walls, Partitions & Doors --------------------------
        (
            "8",
            "8 - Internal Walls, Partitions & Doors",
            {"nrm": "7"},
            [
                ("8.1", "Steel-stud GIB partitions to office (Internal partitions)", "m2", 3800, 138.00, {"nrm": "7.1"}),
                ("8.2", "Fire-rated walls to cores / risers (Fire walls)", "m2", 1400, 178.00, {"nrm": "7.1"}),
                ("8.3", "Acoustic glazed partitions to meeting rooms (Glazed partitions)", "m2", 480, 525.00, {"nrm": "7.2"}),
                ("8.4", "Sanitary cubicle partitions (WC cubicles)", "m2", 220, 320.00, {"nrm": "7.2"}),
                ("8.5", "Solid-core internal doors and frames (Internal doors)", "pcs", 96, 1450.00, {"nrm": "7.3"}),
                ("8.6", "Door hardware sets commercial grade (Door hardware)", "pcs", 96, 580.00, {"nrm": "7.3"}),
            ],
        ),
        # -- 9. Internal Finishes -------------------------------------------
        (
            "9",
            "9 - Internal Finishes",
            {"nrm": "8"},
            [
                ("9.1", "Floor levelling and screed to office (Floor screed)", "m2", 2600, 42.00, {"nrm": "8.1"}),
                ("9.2", "Carpet tile to office areas (Carpet)", "m2", 2100, 78.00, {"nrm": "8.1"}),
                ("9.3", "Vinyl / safety flooring to amenities (Vinyl flooring)", "m2", 520, 95.00, {"nrm": "8.1"}),
                ("9.4", "Polished concrete seal to warehouse (Floor sealer)", "m2", 4200, 28.00, {"nrm": "8.1"}),
                ("9.5", "Ceramic / porcelain tiling to wet areas (Wall & floor tiling)", "m2", 680, 145.00, {"nrm": "8.1"}),
                ("9.6", "Suspended acoustic tile ceiling (Grid ceiling)", "m2", 2400, 88.00, {"nrm": "8.3"}),
                ("9.7", "Plasterboard ceiling and bulkheads (GIB ceilings)", "m2", 900, 96.00, {"nrm": "8.3"}),
                ("9.8", "Painting and decorating throughout (Painting)", "m2", 12500, 32.00, {"nrm": "8.2"}),
                ("9.9", "Wall linings and feature finishes (Feature linings)", "m2", 640, 165.00, {"nrm": "8.2"}),
            ],
        ),
        # -- 10. Fittings, Furnishings & Equipment --------------------------
        (
            "10",
            "10 - Fittings, Furnishings & Equipment (FF&E)",
            {"nrm": "8"},
            [
                ("10.1", "Kitchen / staff breakout joinery (Kitchen joinery)", "m", 48, 1250.00, {"nrm": "8.4"}),
                ("10.2", "Reception and front-of-house joinery (Reception joinery)", "lsum", 1, 78000.00, {"nrm": "8.4"}),
                ("10.3", "Vanities, mirrors and WC accessories (Sanitary fittings)", "pcs", 38, 1450.00, {"nrm": "8.4"}),
                ("10.4", "Signage, wayfinding and statutory (Signage)", "lsum", 1, 64000.00, {"nrm": "8.4"}),
                ("10.5", "Pallet racking and warehouse fitout (Racking)", "lsum", 1, 245000.00, {"nrm": "8.4"}),
                ("10.6", "Window furnishings and blinds (Blinds)", "m2", 1200, 95.00, {"nrm": "8.4"}),
            ],
        ),
        # -- 11. Mechanical Services (HVAC) ---------------------------------
        (
            "11",
            "11 - Mechanical Services (HVAC)",
            {"nrm": "8"},
            [
                ("11.1", "VRF heat-pump air conditioning to office (VRF system)", "m2", 2600, 320.00, {"nrm": "8.1"}),
                ("11.2", "Mechanical ventilation and ductwork (Ductwork)", "m2", 3400, 145.00, {"nrm": "8.1"}),
                ("11.3", "Warehouse destratification and HVLS fans (Warehouse fans)", "pcs", 8, 8500.00, {"nrm": "8.1"}),
                ("11.4", "Outdoor air handling units rooftop (AHU plant)", "pcs", 3, 42000.00, {"nrm": "8.1"}),
                ("11.5", "Exhaust and toilet extract systems (Extract)", "lsum", 1, 56000.00, {"nrm": "8.1"}),
                ("11.6", "Building management system controls (BMS)", "lsum", 1, 185000.00, {"nrm": "8.1"}),
                ("11.7", "Mechanical commissioning and testing (Commissioning)", "lsum", 1, 48000.00, {"nrm": "8.1"}),
            ],
        ),
        # -- 12. Hydraulic & Fire Services ----------------------------------
        (
            "12",
            "12 - Hydraulic & Fire Services",
            {"nrm": "8"},
            [
                ("12.1", "Sanitary plumbing and drainage internal (Internal plumbing)", "m", 1200, 92.00, {"nrm": "8.1"}),
                ("12.2", "Domestic hot and cold water reticulation (Water services)", "m", 1600, 68.00, {"nrm": "8.1"}),
                ("12.3", "Sanitary fixtures and tapware (Sanitaryware)", "pcs", 64, 1250.00, {"nrm": "8.1"}),
                ("12.4", "Gas-fired hot water plant (HW plant)", "pcs", 2, 14500.00, {"nrm": "8.1"}),
                ("12.5", "Fire sprinkler system NZS 4541 (Sprinklers)", "m2", 6800, 58.00, {"nrm": "8.1"}),
                ("12.6", "Fire hydrant and hose-reel system (Hydrants / hose reels)", "lsum", 1, 95000.00, {"nrm": "8.1"}),
                ("12.7", "Fire detection and alarm NZS 4512 (Fire alarm)", "m2", 6800, 32.00, {"nrm": "8.1"}),
                ("12.8", "Stormwater treatment and detention tank (Stormwater)", "lsum", 1, 88000.00, {"nrm": "8.1"}),
            ],
        ),
        # -- 13. Electrical & Communications --------------------------------
        (
            "13",
            "13 - Electrical & Communications",
            {"nrm": "8"},
            [
                ("13.1", "Mains supply, switchboards and distribution (Switchboards)", "lsum", 1, 285000.00, {"nrm": "8.1"}),
                ("13.2", "Sub-mains and final circuits (Power reticulation)", "m2", 6800, 78.00, {"nrm": "8.1"}),
                ("13.3", "LED lighting and emergency lighting (Lighting)", "m2", 6800, 65.00, {"nrm": "8.1"}),
                ("13.4", "Lighting controls and daylight sensors (Lighting controls)", "lsum", 1, 72000.00, {"nrm": "8.1"}),
                ("13.5", "Data cabling, racks and comms room (Structured cabling)", "m2", 2600, 58.00, {"nrm": "8.1"}),
                ("13.6", "Security, access control and CCTV (Security systems)", "lsum", 1, 165000.00, {"nrm": "8.1"}),
                ("13.7", "Rooftop solar PV array 120 kWp (Solar PV)", "lsum", 1, 245000.00, {"nrm": "8.1"}),
                ("13.8", "Passenger lift 13-person MRL (Lift)", "pcs", 2, 175000.00, {"nrm": "8.2"}),
                ("13.9", "EV charging infrastructure (EV chargers)", "pcs", 10, 9500.00, {"nrm": "8.1"}),
            ],
        ),
        # -- 14. External Works & Landscaping -------------------------------
        (
            "14",
            "14 - Siteworks & External Works",
            {"nrm": "9"},
            [
                ("14.1", "Heavy-duty concrete hardstand to yard (Hardstand)", "m2", 3800, 135.00, {"nrm": "9.1"}),
                ("14.2", "Asphalt car park and access roads (Asphalt paving)", "m2", 2600, 78.00, {"nrm": "9.1"}),
                ("14.3", "Kerbs, channels and line marking (Kerbing / marking)", "m", 620, 95.00, {"nrm": "9.1"}),
                ("14.4", "Site stormwater and sewer drainage (Civil drainage)", "m", 880, 165.00, {"nrm": "9.3"}),
                ("14.5", "Site utility connections power / water / gas (Utility connections)", "lsum", 1, 195000.00, {"nrm": "9.4"}),
                ("14.6", "Soft landscaping, planting and irrigation (Landscaping)", "m2", 2200, 58.00, {"nrm": "9.2"}),
                ("14.7", "Boundary fencing and vehicle gates (Fencing / gates)", "m", 480, 185.00, {"nrm": "9.1"}),
                ("14.8", "External lighting to yard and car park (Site lighting)", "pcs", 28, 2850.00, {"nrm": "9.1"}),
                ("14.9", "Bike shelters, bin store and pump stations (Site furniture)", "lsum", 1, 68000.00, {"nrm": "9.1"}),
            ],
        ),
    ],
    markups=[
        ("Preliminaries & General (P&G)", 11.0, "overhead", "direct_cost"),
        ("Margin (Overheads & Profit)", 9.0, "profit", "direct_cost"),
        ("Design & Construction Contingency", 6.0, "contingency", "cumulative"),
        ("GST", 15.0, "tax", "cumulative"),
    ],
    total_months=16,
    tender_name="Main Contract - Design & Build",
    tender_companies=[
        ("Vantrell Construction", "tenders@vantrell.example", 0.98),
        ("Sarraven (Northline Group)", "bids@sarraven.example", 1.05),
        ("TR Kelverstone", "estimating@kelverstone.example", 1.02),
    ],
    project_metadata={
        "address": "12 Highbrook Drive, East Tamaki, Auckland 2013",
        "client": "Eastvane Property Holdings Ltd",
        "architect": "Vellamore Architects",
        "quantity_surveyor": "Marnwick Draysholm Quillane (MDQ)",
        "structural_engineer": "Callensworth Consulting",
        "building_type": "commercial / light-industrial",
        "gfa_m2": 6800,
        "storeys": 2,
        "site_area_ha": 1.1,
        "warehouse_clear_height_m": 9.0,
        "building_code": "NZBC (New Zealand Building Code)",
        "structural_standards": "NZS 3404 (steel), NZS 3101 (concrete), NZS 3604 (timber)",
        "loading_standard": "NZS 1170 / NZS 1170.5 (seismic & loads)",
        "contract": "NZS 3910:2023",
        "importance_level": "IL2",
        "seismic_zone": "Auckland, Z=0.13",
        "wind_region": "A7",
        "sustainability_target": "Green Star 5 Star (NZGBC)",
        "tax_note": "All rates GST exclusive; GST 15% applied as final markup",
    },
    tender_packages=[
        (
            "Main Contract - Design & Build",
            "Full design-and-build delivery under NZS 3910:2023",
            "evaluating",
            [
                ("Vantrell Construction", "tenders@vantrell.example", 0.98),
                ("Sarraven (Northline Group)", "bids@sarraven.example", 1.05),
                ("TR Kelverstone", "estimating@kelverstone.example", 1.02),
            ],
        ),
        (
            "Structural Steel (Frame)",
            "Fabrication and erection of portal / moment frame to NZS 3404",
            "evaluating",
            [
                ("Redmarch Engineering", "tenders@redmarch.example", 0.97),
                ("Draymont Steel Construction", "estimating@draymont.example", 1.04),
                ("Alderay Steel", "bids@alderay.example", 1.01),
            ],
        ),
        (
            "Mechanical & Electrical Services",
            "HVAC, hydraulic, fire and electrical building services",
            "evaluating",
            [
                ("Thermavox NZ", "tenders@thermavox.example", 0.99),
                ("Voltrayne Electrical", "estimating@voltrayne.example", 1.06),
                ("Fernholt Building Services", "bids@fernholt.example", 1.03),
            ],
        ),
        (
            "Civil & External Works",
            "Earthworks, pavements, drainage, utilities and landscaping",
            "evaluating",
            [
                ("Kalverton Civil", "tenders@kalverton.example", 0.98),
                ("Trentmoor Contractors", "estimating@trentmoor.example", 1.05),
            ],
        ),
    ],
)
