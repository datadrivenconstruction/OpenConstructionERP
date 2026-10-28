# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Flagship demo: Secondary school with seismic base isolation, Christchurch (NZ)
# ---------------------------------------------------------------------------
# Post-earthquake rebuild of a state secondary school in Christchurch. Designed
# and procured the way a New Zealand quantity surveyor would price it: an
# elemental cost plan to NRM 1 conventions (NZIQS practice), measured trades,
# building consent under the New Zealand Building Code (NZBC). Structure designed
# to NZS 3404 (steel), NZS 3101 (concrete) and the timber standards NZS 3603 /
# NZS 3604, with engineered timber (LVL portals and CLT floors / shear walls)
# to AS/NZS 1328. Loads and earthquake actions to NZS 1170 / NZS 1170.5.
#
# Because schools are critical post-disaster facilities, the buildings are
# designed to Importance Level 3 (assembly / many occupants) with the gym and
# hall acting as a community Civil Defence shelter (Importance Level 4 detailing
# on the egress and services routes). The whole site sits on lead-rubber
# bearings and flat sliders, so the superstructure is base isolated above a
# stiff foundation diaphragm - the post-2011 Canterbury rebuild approach.
#
# Procurement follows the Ministry of Education property design standards
# (DQLS designation, Te Rautaki Rawa Kura / Designing Schools in New Zealand,
# the Acoustic and IAQ guidelines) and an ECI / NZS 3910:2023 head contract.
# All rates are NZD, GST exclusive, at Christchurch Q1 2026 price level. GST
# (15%) is carried as a separate cumulative markup, never baked into the rates.
#
# Program: a 1,100-roll co-educational secondary school (Years 9-13) of approx.
# 11,800 m2 GFA across four linked, base-isolated blocks - two two-storey
# Innovative Learning Environment teaching blocks, a specialist science / arts
# / technology block, a double-court gymnasium, and a 600-seat assembly hall /
# performing-arts space - plus hard courts, fields and external works on a
# 4.2 ha greenfield platform. Importance Level 3, Canterbury seismic hazard
# (Z=0.30, soil Class D / deep alluvium), wind region A6. Headline construction
# cost circa NZD 66 million (GST exclusive).

TEMPLATE = DemoTemplate(
    demo_id="school-christchurch",
    project_name="Secondary School - Christchurch (Waitaha College)",
    project_description=(
        "New 1,100-roll co-educational secondary school (Years 9-13) on a 4.2 ha "
        "greenfield platform at Wigram, Christchurch, delivered as part of the "
        "Canterbury post-earthquake schools rebuild. Approx. 11,800 m2 GFA across "
        "four linked, seismically base-isolated blocks: two two-storey Innovative "
        "Learning Environment teaching blocks, a specialist science / technology / "
        "arts block, a double-court gymnasium and a 600-seat assembly hall and "
        "performing-arts space. Engineered-timber superstructure - LVL moment "
        "portals (AS/NZS 1328) with CLT floor cassettes and shear walls - on a "
        "reinforced-concrete foundation diaphragm, with the whole structure carried "
        "on lead-rubber bearings and flat sliders. Designed to NZS 1170 / NZS "
        "1170.5 at Importance Level 3 (gym and hall detailed to IL4 as a Civil "
        "Defence community shelter), Canterbury seismic hazard Z=0.30 on soil Class "
        "D, wind region A6. NZBC compliant and built to the Ministry of Education "
        "property design standards (Designing Schools in New Zealand, DQLS, the "
        "Acoustic and Indoor Air Quality guidelines). ECI head contract under NZS "
        "3910:2023, Green Star 5 Star Education target. Estimated construction cost "
        "circa NZD 66M (GST excl.)."
    ),
    region="NZ",
    classification_standard="nrm",
    currency="NZD",
    locale="en-NZ",
    address={
        "street": "120 Awatea Road, Wigram",
        "city": "Christchurch",
        "postcode": "8042",
        "country": "New Zealand",
        "lat": -43.5462,
        "lng": 172.5419,
    },
    validation_rule_sets=["nrm", "boq_quality"],
    boq_name="Elemental Cost Plan - NRM 1 (NZ)",
    boq_description=(
        "Elemental cost plan to NRM 1 conventions (NZIQS practice), measured "
        "trades; NZ Building Code compliant, MoE property standards, base "
        "isolated, NZS 3910:2023 ECI head contract"
    ),
    boq_metadata={
        "standard": "NRM 1 (elemental) / NZS 4202 measurement",
        "phase": "Developed Design Cost Plan",
        "base_date": "2026-Q1",
        "price_level": "Christchurch 2026 (NZD, GST excl.)",
    },
    sections=[
        # -- 1. Preliminaries & General -------------------------------------
        (
            "1",
            "1 - Preliminaries & General (P&G)",
            {"nrm": "0"},
            [
                ("1.1", "Site establishment and disestablishment (Site set-up)", "lsum", 1, 285000.00, {"nrm": "0.1"}),
                ("1.2", "Site offices, amenities and ablutions (Site offices)", "month", 24, 8200.00, {"nrm": "0.1"}),
                ("1.3", "Site management and supervision (Staffing)", "month", 24, 52000.00, {"nrm": "0.1"}),
                ("1.4", "Temporary fencing, hoarding and pedestrian protection (Site security)", "m", 980, 52.00, {"nrm": "0.1"}),
                ("1.5", "Mobile and crawler cranage for timber lifts (Cranage)", "month", 16, 32000.00, {"nrm": "0.1"}),
                ("1.6", "Scaffolding, edge protection and fall arrest (Scaffold)", "m2", 6400, 42.00, {"nrm": "0.1"}),
                ("1.7", "Health, safety and traffic management plan (H&S / TMP)", "lsum", 1, 235000.00, {"nrm": "0.1"}),
                ("1.8", "Resource and building consent fees, MoE / CCC (Consent fees)", "lsum", 1, 285000.00, {"nrm": "0.1"}),
                ("1.9", "Surveying, set-out and base-isolation control survey (Setting out)", "lsum", 1, 72000.00, {"nrm": "0.1"}),
                ("1.10", "ECI design coordination and BIM management (ECI / BIM)", "lsum", 1, 165000.00, {"nrm": "0.1"}),
            ],
        ),
        # -- 2. Site Preparation & Earthworks -------------------------------
        (
            "2",
            "2 - Site Preparation & Earthworks",
            {"nrm": "0"},
            [
                ("2.1", "Geotechnical investigation, CPT and liquefaction report (Ground investigation)", "lsum", 1, 96000.00, {"nrm": "0.3"}),
                ("2.2", "Site clearance, demolition and topsoil strip (Clearing / strip)", "m2", 42000, 7.20, {"nrm": "0.1"}),
                ("2.3", "Bulk earthworks cut and fill to platform (Bulk earthworks)", "m3", 38000, 19.50, {"nrm": "0.2"}),
                ("2.4", "Stone-column / RIC ground improvement to liquefiable soils (Ground improvement)", "m2", 12800, 88.00, {"nrm": "0.2"}),
                ("2.5", "Cart surplus and unsuitable spoil to disposal (Spoil cartage)", "m3", 16500, 36.00, {"nrm": "0.2"}),
                ("2.6", "Import and compact engineered hardfill AP65 (Engineered fill)", "m3", 14200, 64.00, {"nrm": "0.2"}),
                ("2.7", "Erosion and sediment control to ECan rules (ESC measures)", "lsum", 1, 92000.00, {"nrm": "0.1"}),
                ("2.8", "Subgrade trim, proof roll and undercut (Subgrade prep)", "m2", 16800, 8.40, {"nrm": "0.2"}),
            ],
        ),
        # -- 3. Substructure, Foundations & Base Isolation ------------------
        (
            "3",
            "3 - Substructure, Foundations & Base Isolation (NZS 3101 / NZS 1170.5)",
            {"nrm": "1"},
            [
                ("3.1", "Mass excavation to foundation diaphragm and pits (Foundation excavation)", "m3", 9800, 26.00, {"nrm": "1.1"}),
                ("3.2", "Bored RC piles 900 mm to founding stratum (Bored piles)", "m", 2200, 285.00, {"nrm": "1.1"}),
                ("3.3", "RC pile caps and isolator plinths 40 MPa (Pile caps / plinths)", "m3", 1180, 410.00, {"nrm": "1.1"}),
                ("3.4", "RC ground beams to isolation diaphragm (Ground beams)", "m3", 640, 380.00, {"nrm": "1.1"}),
                ("3.5", "Reinforcing steel Grade 500E to substructure (Rebar)", "t", 268, 3650.00, {"nrm": "1.1"}),
                ("3.6", "Lead-rubber bearings 700 mm dia, supply and install (LRB isolators)", "pcs", 96, 18500.00, {"nrm": "1.1"}),
                ("3.7", "PTFE flat slider bearings, supply and install (Sliding isolators)", "pcs", 64, 9800.00, {"nrm": "1.1"}),
                ("3.8", "Stainless tie-down and shear-key assemblies cast-in (Restraint hardware)", "pcs", 160, 1450.00, {"nrm": "1.1"}),
                ("3.9", "Isolation seismic gap, moat cover and flexible joints (Seismic gap / moat)", "m", 460, 720.00, {"nrm": "1.1"}),
                ("3.10", "Flexible service crossings over isolation plane (Flexible services)", "lsum", 1, 245000.00, {"nrm": "1.1"}),
                ("3.11", "Ground-bearing slab 200 mm to ground floors SOG (Ground slab)", "m2", 6800, 158.00, {"nrm": "1.2"}),
                ("3.12", "Suspended CLT / concrete topping to upper floors (Suspended floor)", "m2", 5200, 235.00, {"nrm": "1.2"}),
                ("3.13", "DPM and under-slab vapour barrier (Damp-proof membrane)", "m2", 6800, 10.50, {"nrm": "1.2"}),
                ("3.14", "Sub-slab insulation XPS R2.0 to teaching blocks (Slab insulation)", "m2", 6800, 32.00, {"nrm": "1.2"}),
            ],
        ),
        # -- 4. Structural Frame, Upper Floors & Roof (Engineered Timber + Steel)
        (
            "4",
            "4 - Frame, Upper Floors & Roof Structure (LVL / CLT timber + NZS 3404 steel)",
            {"nrm": "2"},
            [
                ("4.1", "LVL moment-resisting portal frames, supply and install (LVL portals)", "m3", 920, 3850.00, {"nrm": "2.1"}),
                ("4.2", "Glulam columns and primary beams (Glulam framing)", "m3", 540, 3650.00, {"nrm": "2.1"}),
                ("4.3", "CLT shear walls 5-ply to lateral system (CLT shear walls)", "m2", 4200, 285.00, {"nrm": "2.1"}),
                ("4.4", "Pres-Lam post-tensioned rocking frame and PT bars (Pres-Lam system)", "lsum", 1, 685000.00, {"nrm": "2.1"}),
                ("4.5", "Ductile steel U-shaped flexural plate dissipaters (UFP dampers)", "pcs", 240, 2850.00, {"nrm": "2.1"}),
                ("4.6", "Structural steel transfer beams and braces to gym (Steel framing)", "t", 185, 5950.00, {"nrm": "2.1"}),
                ("4.7", "Proprietary timber connection brackets and bolts (Connections)", "pcs", 3800, 145.00, {"nrm": "2.1"}),
                ("4.8", "Erect and crane-set timber superstructure (Timber erection)", "m3", 1460, 920.00, {"nrm": "2.1"}),
                ("4.9", "CLT floor cassettes with acoustic resilient topping (Timber floor cassettes)", "m2", 5200, 268.00, {"nrm": "2.3"}),
                ("4.10", "Steel and timber stairs, landings and egress stairs (Stairs)", "pcs", 12, 33500.00, {"nrm": "2.4"}),
                ("4.11", "Stair and balcony balustrades, glass and stainless (Balustrades)", "m", 320, 345.00, {"nrm": "2.4"}),
                ("4.12", "Long-span timber roof framing and diaphragm to hall / gym (Long-span roof)", "m3", 380, 3950.00, {"nrm": "2.5"}),
            ],
        ),
        # -- 5. External Envelope (Walls, Cladding, Roof, Openings) ---------
        (
            "5",
            "5 - Envelope (External Walls, Cladding, Roof, Windows & Doors)",
            {"nrm": "5"},
            [
                ("5.1", "Light-timber-frame external walls to NZS 3604 (Timber-frame walls)", "m2", 6800, 165.00, {"nrm": "5.1"}),
                ("5.2", "Rigid air barrier and weather-resistive membrane (Air / weather barrier)", "m2", 9200, 26.00, {"nrm": "5.1"}),
                ("5.3", "Continuous external rigid insulation R3.0 (Wall insulation)", "m2", 9200, 42.00, {"nrm": "5.1"}),
                ("5.4", "Fibre-cement vertical-batten rainscreen cladding (FC rainscreen)", "m2", 4200, 215.00, {"nrm": "5.1"}),
                ("5.5", "Brick veneer and cedar feature cladding (Feature cladding)", "m2", 2580, 315.00, {"nrm": "5.1"}),
                ("5.6", "Long-run pre-painted steel roofing 0.55 BMT (Metal roofing)", "m2", 7200, 92.00, {"nrm": "4.1"}),
                ("5.7", "Roof insulation R6.0 and safety mesh (Roof insulation)", "m2", 7200, 38.00, {"nrm": "4.2"}),
                ("5.8", "Roof flashings, gutters, spouting and downpipes (Flashings / rainwater)", "m", 2200, 72.00, {"nrm": "4.1"}),
                ("5.9", "Thermally broken aluminium windows, double-glazed IGU (Windows)", "m2", 2400, 565.00, {"nrm": "6.1"}),
                ("5.10", "Aluminium curtain wall to atrium and entries (Curtain wall)", "m2", 760, 695.00, {"nrm": "6.1"}),
                ("5.11", "Glazed automatic entrances and external doors (External doors)", "pcs", 43, 5650.00, {"nrm": "6.3"}),
                ("5.12", "Operable solar-shading and brise-soleil (External shading)", "m2", 640, 385.00, {"nrm": "6.1"}),
            ],
        ),
        # -- 6. Internal Walls, Partitions & Doors --------------------------
        (
            "6",
            "6 - Internal Walls, Partitions & Doors",
            {"nrm": "7"},
            [
                ("6.1", "Steel-stud GIB partitions to learning spaces (Internal partitions)", "m2", 8600, 142.00, {"nrm": "7.1"}),
                ("6.2", "Inter-tenancy acoustic walls STC 50 between classes (Acoustic walls)", "m2", 4200, 188.00, {"nrm": "7.1"}),
                ("6.3", "Fire-rated walls to cores, risers and exits (Fire walls)", "m2", 2800, 196.00, {"nrm": "7.1"}),
                ("6.4", "Operable acoustic sliding folding walls (Operable walls)", "m2", 680, 720.00, {"nrm": "7.2"}),
                ("6.5", "Glazed internal partitions to breakout / shared (Glazed partitions)", "m2", 1100, 525.00, {"nrm": "7.2"}),
                ("6.6", "Sanitary cubicle and shower partition systems (WC / shower cubicles)", "m2", 520, 345.00, {"nrm": "7.2"}),
                ("6.7", "Solid-core internal doors with commercial hardware (Internal doors / hardware)", "pcs", 240, 2070.00, {"nrm": "7.3"}),
            ],
        ),
        # -- 7. Internal Finishes -------------------------------------------
        (
            "7",
            "7 - Internal Finishes",
            {"nrm": "8"},
            [
                ("7.1", "Floor levelling and screed to learning spaces (Floor screed)", "m2", 8200, 44.00, {"nrm": "8.1"}),
                ("7.2", "Carpet tile to classrooms and offices (Carpet)", "m2", 6200, 82.00, {"nrm": "8.1"}),
                ("7.3", "Vinyl and safety flooring to wet / circulation (Vinyl flooring)", "m2", 2600, 98.00, {"nrm": "8.1"}),
                ("7.4", "Polished and sealed concrete to technology / atrium (Sealed concrete)", "m2", 1800, 58.00, {"nrm": "8.1"}),
                ("7.5", "Ceramic and porcelain tiling to wet areas (Wall & floor tiling)", "m2", 1450, 152.00, {"nrm": "8.1"}),
                ("7.6", "Suspended acoustic tile ceiling NRC rated (Grid ceiling)", "m2", 6400, 92.00, {"nrm": "8.3"}),
                ("7.7", "Exposed CLT soffit clear-finished (Exposed timber ceiling)", "m2", 3200, 48.00, {"nrm": "8.3"}),
                ("7.8", "Plasterboard ceilings, bulkheads and seismic bracing (GIB ceilings)", "m2", 2200, 108.00, {"nrm": "8.3"}),
                ("7.9", "Painting and decorating throughout (Painting)", "m2", 24000, 34.00, {"nrm": "8.2"}),
                ("7.10", "Impact-resistant wall linings and acoustic panels (Wall linings / panels)", "m2", 4250, 145.00, {"nrm": "8.2"}),
            ],
        ),
        # -- 8. Fittings, Furnishings & Equipment ---------------------------
        (
            "8",
            "8 - Fittings, Furnishings & Equipment (FF&E)",
            {"nrm": "8"},
            [
                ("8.1", "Classroom and ILE built-in joinery, walls of storage (Learning-space joinery)", "m", 720, 1180.00, {"nrm": "8.4"}),
                ("8.2", "Library / learning-commons joinery and shelving (Library fitout)", "lsum", 1, 165000.00, {"nrm": "8.4"}),
                ("8.3", "Staffroom and administration joinery (Admin joinery)", "m", 140, 1250.00, {"nrm": "8.4"}),
                ("8.4", "Vanities, mirrors and accessible WC accessories (Sanitary fittings)", "pcs", 96, 1450.00, {"nrm": "8.4"}),
                ("8.5", "Signage, wayfinding, bicultural and statutory (Signage)", "lsum", 1, 145000.00, {"nrm": "8.4"}),
                ("8.6", "Window furnishings, blinds and blackout (Blinds)", "m2", 2400, 98.00, {"nrm": "8.4"}),
                ("8.7", "Whiteboards, pinboards and AV display joinery (Teaching walls)", "pcs", 110, 1850.00, {"nrm": "8.4"}),
            ],
        ),
        # -- 9. Specialist: Science Labs, Gymnasium, Hall & Performing Arts --
        (
            "9",
            "9 - Specialist: Science Labs, Gymnasium, Hall & Performing Arts",
            {"nrm": "8"},
            [
                ("9.1", "Science laboratory benches and fume cupboards (Lab fitout)", "pcs", 12, 38500.00, {"nrm": "8.4"}),
                ("9.2", "Technology / hard-materials workshop benching (Workshop fitout)", "m", 180, 1650.00, {"nrm": "8.4"}),
                ("9.3", "Food technology / commercial teaching kitchen (Food-tech kitchen)", "lsum", 1, 285000.00, {"nrm": "8.4"}),
                ("9.4", "Double-court sprung sports flooring system (Sports flooring)", "m2", 1280, 215.00, {"nrm": "8.4"}),
                ("9.5", "Retractable tiered seating to hall, 600 seats (Retractable seating)", "pcs", 600, 720.00, {"nrm": "8.4"}),
                ("9.6", "Gymnasium sports equipment, hoops and dividers (Sports equipment)", "lsum", 1, 245000.00, {"nrm": "8.4"}),
                ("9.7", "Performing-arts stage, rigging and AV lighting (Stage / theatre rig)", "lsum", 1, 385000.00, {"nrm": "8.4"}),
                ("9.8", "Hall and gym acoustic treatment, padding and rebound (Acoustic / protection)", "m2", 2370, 175.00, {"nrm": "8.4"}),
                ("9.9", "Civil-defence shelter provisions, gym and hall (Shelter provisions)", "lsum", 1, 165000.00, {"nrm": "8.4"}),
            ],
        ),
        # -- 10. Mechanical, Hydraulic & Fire Services ----------------------
        (
            "10",
            "10 - Mechanical (HVAC / IAQ), Hydraulic & Fire Services",
            {"nrm": "8"},
            [
                ("10.1", "VRF heat-pump heating and cooling to learning spaces (VRF system)", "m2", 8200, 345.00, {"nrm": "8.1"}),
                ("10.2", "Balanced mechanical ventilation with heat recovery (MVHR / ductwork)", "m2", 11800, 165.00, {"nrm": "8.1"}),
                ("10.3", "CO2-demand IAQ control to MoE guidelines (IAQ controls)", "lsum", 1, 185000.00, {"nrm": "8.1"}),
                ("10.4", "Science fume extract, kitchen and workshop exhaust (Specialist extract)", "lsum", 1, 311000.00, {"nrm": "8.1"}),
                ("10.5", "Building management system and commissioning (BMS / commissioning)", "lsum", 1, 373000.00, {"nrm": "8.1"}),
                ("10.6", "Sanitary plumbing, drainage, water and HW plant (Plumbing / water / HW)", "m", 5200, 97.00, {"nrm": "8.1"}),
                ("10.7", "Sanitary fixtures, tapware and troughs (Sanitaryware)", "pcs", 180, 1280.00, {"nrm": "8.1"}),
                ("10.8", "Fire sprinkler system NZS 4541 (Sprinklers)", "m2", 11800, 56.00, {"nrm": "8.1"}),
                ("10.9", "Fire hydrant, hose-reel and rainwater reuse (Hydrants / rainwater)", "lsum", 1, 237000.00, {"nrm": "8.1"}),
                ("10.10", "Fire detection, alarm and evacuation NZS 4512 (Fire alarm)", "m2", 11800, 34.00, {"nrm": "8.1"}),
            ],
        ),
        # -- 11. Electrical, Data & Communications --------------------------
        (
            "11",
            "11 - Electrical, Data & Communications",
            {"nrm": "8"},
            [
                ("11.1", "Mains supply, main switchboard and distribution (Switchboards)", "lsum", 1, 345000.00, {"nrm": "8.1"}),
                ("11.2", "Sub-mains, final circuits and seismic-restrained tray (Power reticulation)", "m2", 11800, 82.00, {"nrm": "8.1"}),
                ("11.3", "LED lighting to learning, sports and circulation (Lighting)", "m2", 11800, 68.00, {"nrm": "8.1"}),
                ("11.4", "Lighting, daylight and Civil-Defence egress controls (Lighting controls)", "lsum", 1, 174000.00, {"nrm": "8.1"}),
                ("11.5", "Structured data cabling, racks and comms rooms (Structured cabling)", "m2", 11800, 52.00, {"nrm": "8.1"}),
                ("11.6", "WiFi, AV and classroom display systems (AV / WiFi)", "lsum", 1, 285000.00, {"nrm": "8.1"}),
                ("11.7", "Security, access control, intruder and CCTV (Security systems)", "lsum", 1, 235000.00, {"nrm": "8.1"}),
                ("11.8", "PA, intercom and bell / lockdown system (PA / lockdown)", "lsum", 1, 125000.00, {"nrm": "8.1"}),
                ("11.9", "Rooftop solar PV array 200 kWp (Solar PV)", "lsum", 1, 385000.00, {"nrm": "8.1"}),
                ("11.10", "Standby generator, post-disaster supply and EV charging (Generator / EV)", "lsum", 1, 359000.00, {"nrm": "8.1"}),
            ],
        ),
        # -- 12. Siteworks, Courts & External Works -------------------------
        (
            "12",
            "12 - Siteworks, Courts & External Works",
            {"nrm": "9"},
            [
                ("12.1", "Asphalt access roads, bus bay and car parks (Asphalt paving)", "m2", 8600, 78.00, {"nrm": "9.1"}),
                ("12.2", "Concrete courts and multi-use hard courts (Hard courts)", "m2", 3200, 138.00, {"nrm": "9.1"}),
                ("12.3", "Acrylic court surfacing and line marking (Court surfacing)", "m2", 3200, 58.00, {"nrm": "9.1"}),
                ("12.4", "Concrete paths, covered walkways and canopies (Paths / canopies)", "m2", 4200, 165.00, {"nrm": "9.1"}),
                ("12.5", "Sports field formation, drainage and turf (Sports fields)", "m2", 14000, 42.00, {"nrm": "9.2"}),
                ("12.6", "Soft landscaping, native planting and irrigation (Landscaping)", "m2", 6800, 56.00, {"nrm": "9.2"}),
                ("12.7", "Site stormwater, soakage and detention (Civil drainage)", "m", 1850, 175.00, {"nrm": "9.3"}),
                ("12.8", "Site utility connections power / water / comms (Utility connections)", "lsum", 1, 285000.00, {"nrm": "9.4"}),
                ("12.9", "Boundary fencing, ball-stop and vehicle gates (Fencing / gates)", "m", 1280, 165.00, {"nrm": "9.1"}),
                ("12.10", "External lighting to courts, paths and car parks (Site lighting)", "pcs", 56, 2850.00, {"nrm": "9.1"}),
                ("12.11", "Playground, outdoor learning, cycle shelters and site furniture (Outdoor / furniture)", "lsum", 1, 261000.00, {"nrm": "9.2"}),
            ],
        ),
    ],
    markups=[
        ("Preliminaries & General (P&G)", 12.0, "overhead", "direct_cost"),
        ("Margin (Overheads & Profit)", 8.5, "profit", "direct_cost"),
        ("Design & Construction Contingency", 8.0, "contingency", "cumulative"),
        ("GST", 15.0, "tax", "cumulative"),
    ],
    total_months=24,
    tender_name="Main Contract - ECI / Construct (NZS 3910:2023)",
    tender_companies=[
        ("Ashmount Construction", "tenders@ashmount.example", 0.99),
        ("Vantrell Construction", "tenders@vantrell.example", 0.97),
        ("Brayford Construction", "estimating@brayford.example", 1.01),
        ("Sarraven (Northline Group)", "bids@sarraven.example", 1.04),
    ],
    project_metadata={
        "address": "120 Awatea Road, Wigram, Christchurch 8042",
        "client": "Ministry of Education - Te Tāhuhu o te Mātauranga",
        "architect": "Vellamore Architects",
        "quantity_surveyor": "Marnwick Draysholm Quillane (MDQ)",
        "structural_engineer": "Callensworth Consulting",
        "base_isolation_engineer": "Vanmoor Seismic (VMS)",
        "building_type": "education / secondary school",
        "school_roll": 1100,
        "year_levels": "Years 9-13",
        "gfa_m2": 11800,
        "storeys": 2,
        "site_area_ha": 4.2,
        "blocks": "2x ILE teaching blocks, specialist science/tech/arts block, gymnasium, 600-seat hall",
        "building_code": "NZBC (New Zealand Building Code)",
        "structural_standards": "NZS 3404 (steel), NZS 3101 (concrete), NZS 3603 / NZS 3604 (timber), AS/NZS 1328 (glulam/LVL)",
        "loading_standard": "NZS 1170 / NZS 1170.5 (seismic & loads)",
        "moe_standards": "Designing Schools in New Zealand; DQLS; MoE Acoustic & Indoor Air Quality guidelines",
        "contract": "NZS 3910:2023 (ECI then construct)",
        "importance_level": "IL3 (gym & hall detailed to IL4 - Civil Defence shelter)",
        "seismic_system": "Base isolation - lead-rubber bearings + flat sliders; LVL/CLT Pres-Lam rocking frames with UFP dampers",
        "seismic_zone": "Christchurch (Canterbury), Z=0.30, soil Class D",
        "wind_region": "A6",
        "sustainability_target": "Green Star 5 Star Education (NZGBC)",
        "tax_note": "All rates GST exclusive; GST 15% applied as final markup",
    },
    tender_packages=[
        (
            "Main Contract - ECI / Construct (NZS 3910:2023)",
            "Early-contractor-involvement then construct delivery of all blocks and site",
            "evaluating",
            [
                ("Ashmount Construction", "tenders@ashmount.example", 0.99),
                ("Vantrell Construction", "tenders@vantrell.example", 0.97),
                ("Brayford Construction", "estimating@brayford.example", 1.01),
                ("Sarraven (Northline Group)", "bids@sarraven.example", 1.04),
            ],
        ),
        (
            "Base Isolation & Foundations",
            "Ground improvement, foundation diaphragm, lead-rubber bearings and sliders",
            "evaluating",
            [
                ("Vanmoor Seismic (VMS)", "tenders@vanmoor.example", 0.98),
                ("Kalverton Civil", "estimating@kalverton.example", 1.03),
                ("Ostwick Construction", "bids@ostwick.example", 1.01),
            ],
        ),
        (
            "Engineered Timber Superstructure",
            "LVL / glulam portals, CLT floors and shear walls, Pres-Lam rocking frames",
            "evaluating",
            [
                ("Kaurex Timberworks", "tenders@kaurex.example", 0.98),
                ("Beamora NZ", "estimating@beamora.example", 1.05),
                ("Velcross New Zealand", "bids@velcross.example", 1.02),
            ],
        ),
        (
            "Mechanical & Electrical Services",
            "HVAC / IAQ, hydraulic, fire, electrical, data and AV building services",
            "evaluating",
            [
                ("Thermavox NZ", "tenders@thermavox.example", 0.99),
                ("Delwyn / Corrantes Services", "estimating@delwyn.example", 1.06),
                ("Fernholt Building Services", "bids@fernholt.example", 1.03),
            ],
        ),
        (
            "Civil & External Works",
            "Earthworks, courts, fields, pavements, drainage, utilities and landscaping",
            "evaluating",
            [
                ("Kalverton Civil", "tenders@kalverton.example", 0.98),
                ("Tarnley Construction", "estimating@tarnley.example", 1.04),
                ("Redhollow Earthmoving", "bids@redhollow.example", 1.02),
            ],
        ),
    ],
    budget_boq_name="Elemental Cost Plan - NRM 1 (NZ)",
    planned_budget=72000000.0,
    actual_spend_ratio=0.42,
    spi_override=0.97,
    cpi_override=1.02,
)
