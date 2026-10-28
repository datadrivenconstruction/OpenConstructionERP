# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo pack: Volumetric Modular Housing Scheme (offsite / DfMA)
# ---------------------------------------------------------------------------
# A 120-unit modular apartment block delivered as steel volumetric modules,
# factory-built then craned and stitched together on site. The BOQ is split
# into FACTORY scope (module fabrication, off-site) and SITE scope (enabling,
# foundations, craneage & installation, weather-tightness, MEP stitching,
# facade and commissioning).
#
# Classification: NRM 1 elements are used to keep the scheme legible to a UK/EU
# quantity surveyor, with a FACTORY/SITE work-breakdown layered on top - this
# mirrors how offsite cost plans are usually presented (split by where the
# value is created, then mapped back to elements for benchmarking).
#
# Program (headline):
#   120 apartments (mix 1B2P / 2B4P), 8 storeys above a transfer podium.
#   234 volumetric modules (light-gauge steel chassis, ~3.4 m x 8.5 m).
#   GIA ~ 9,250 m2, treated floor area ~ 7,400 m2.
#   ~ 65% of value manufactured offsite (DfMA), 8-day-per-floor cycle on site.
#   Fabric energy class EPC A / nZEB, MMC Category 1 (3D primary structural).
#   Headline construction cost ~ EUR 27.4M (~ EUR 2,960 / m2 GIA).
#
# Standards / compliance refs:
#   EN 1090-2 (EXC2) steel execution, EN 1993 / EN 1995 design,
#   ICC/MBI 1200 (off-site planning, prefab inspection) & 1205 (off-site
#   construction inspection & regulatory compliance), CSA A277 (certification
#   of factory-built buildings) for the factory QC regime,
#   EN 12811 temporary works for craneage, abnormal-load transport per
#   EU Directive 96/53/EC, EN 1991-1-4 wind for installation lifts.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="modular-housing",
    project_name="Riverside Modular Quarter",
    project_description=(
        "120-unit volumetric modular apartment scheme delivered by DfMA. "
        "234 light-gauge steel volumetric modules (~3.4 m x 8.5 m) factory-built, "
        "then craned and stitched over 8 storeys on a reinforced-concrete transfer "
        "podium. Unit mix 1B2P / 2B4P. GIA ~9,250 m2, ~7,400 m2 treated. "
        "EPC A / nZEB fabric, MMC Category 1 (3D primary structural). "
        "Steel execution EN 1090-2 (EXC2); factory QC to ICC/MBI 1200/1205 and "
        "CSA A277. ~65% of value manufactured offsite. Headline cost ~EUR 27.4M."
    ),
    region="EU",
    classification_standard="nrm",
    currency="EUR",
    locale="en",
    address={
        # Real address: NDSM Wharf, Amsterdam-Noord - an established hub for
        # large-scale volumetric / offsite residential delivery in the EU.
        "street": "NDSM-Plein 28",
        "city": "Amsterdam",
        "postcode": "1033 WB",
        "country": "Netherlands",
        "lat": 52.4012,
        "lng": 4.8946,
    },
    validation_rule_sets=["nrm", "boq_quality"],
    boq_name="Offsite Cost Plan - NRM 1 (Factory + Site)",
    boq_description=(
        "Elemental cost plan per NRM 1 (3rd Edition) for a volumetric modular "
        "housing scheme, split into FACTORY (offsite module fabrication) and SITE "
        "(enabling, foundations, installation, weathering, MEP stitch, commissioning)."
    ),
    boq_metadata={
        "standard": "NRM 1 (3rd Edition, 2021) + DfMA work-breakdown",
        "phase": "RIBA Stage 4 / MMC Stage 2 Cost Plan",
        "base_date": "2026-Q1",
        "price_level": "EU 2026",
        "modules": 234,
        "units": 120,
        "offsite_value_pct": 65,
        "mmc_category": "Category 1 (3D primary structural)",
    },
    sections=[
        # ===================================================================
        # FACTORY SCOPE  (offsite module fabrication)
        # ===================================================================
        # -- F1 Factory mobilisation, engineering & QC ----------------------
        (
            "F1",
            "FACTORY - F1 Engineering, Production Engineering & QC",
            {"nrm": "0"},
            [
                ("F1.1", "DfMA design & module production drawings (offsite engineering)", "lsum", 1, 285000.00, {"nrm": "0.4"}),
                ("F1.2", "Module type prototyping & first-article inspection (ICC/MBI 1200)", "pcs", 4, 38000.00, {"nrm": "0.4"}),
                ("F1.3", "Factory production-line set-up & jig tooling per module type", "pcs", 4, 22000.00, {"nrm": "0.4"}),
                ("F1.4", "In-plant QA/QC inspection regime (CSA A277 / ICC-MBI 1205)", "month", 9, 18500.00, {"nrm": "0.4"}),
                ("F1.5", "EN 1090-2 EXC2 factory production control certification", "lsum", 1, 32000.00, {"nrm": "0.4"}),
                ("F1.6", "BIM module library & digital twin coordination (LOD 400)", "lsum", 1, 64000.00, {"nrm": "0.4"}),
            ],
        ),
        # -- F2 Structural chassis (light-gauge steel volumetric frame) -----
        (
            "F2",
            "FACTORY - F2 Structural Chassis (steel volumetric frame)",
            {"nrm": "2"},
            [
                ("F2.1", "Light-gauge steel module chassis fabrication (cold-formed sections)", "t", 1170, 2850.00, {"nrm": "2.1"}),
                ("F2.2", "Corner posts & SHS load-path columns EN 1993 (vertical load transfer)", "t", 295, 3450.00, {"nrm": "2.1"}),
                ("F2.3", "Floor cassette assembly (steel joists + acoustic deck)", "m2", 6630, 78.00, {"nrm": "2.1"}),
                ("F2.4", "Ceiling cassette assembly (steel joists + fire board carrier)", "m2", 6630, 62.00, {"nrm": "2.1"}),
                ("F2.5", "Welded & bolted module connections EN 1090-2 (factory welding EXC2)", "pcs", 234, 1450.00, {"nrm": "2.3"}),
                ("F2.6", "Intumescent / cementitious fire protection to chassis (R60)", "m2", 7400, 24.00, {"nrm": "2.4"}),
                ("F2.7", "Hot-dip galvanising / shop priming of steel chassis", "t", 1170, 420.00, {"nrm": "2.4"}),
            ],
        ),
        # -- F3 Module envelope (factory-applied) ---------------------------
        (
            "F3",
            "FACTORY - F3 Module Envelope (factory-applied)",
            {"nrm": "5"},
            [
                ("F3.1", "External wall panel build-up (SFS + sheathing + breather)", "m2", 8900, 96.00, {"nrm": "5.1"}),
                ("F3.2", "Mineral-wool thermal insulation to external walls (U ≤ 0.18)", "m2", 8900, 28.00, {"nrm": "5.1"}),
                ("F3.3", "Inter-module acoustic separation (resilient layer, party walls)", "m2", 9600, 34.00, {"nrm": "7.1"}),
                ("F3.4", "Inter-module fire-stopping cavity barriers (factory)", "m", 4680, 22.00, {"nrm": "5.1"}),
                ("F3.5", "Factory-fitted windows (triple-glazed Uw ≤ 0.9, Aw class 4)", "pcs", 384, 720.00, {"nrm": "6.1"}),
                ("F3.6", "Factory-fitted external apartment / balcony doors", "pcs", 156, 980.00, {"nrm": "6.2"}),
            ],
        ),
        # -- F4 MEP first-fix (in-module) -----------------------------------
        (
            "F4",
            "FACTORY - F4 MEP First-Fix (in-module)",
            {"nrm": "8"},
            [
                ("F4.1", "In-module electrical first-fix (containment, wiring, back-boxes)", "pcs", 234, 3650.00, {"nrm": "8.2"}),
                ("F4.2", "Consumer unit & module distribution board (per module)", "pcs", 234, 480.00, {"nrm": "8.2"}),
                ("F4.3", "In-module plumbing first-fix (hot/cold, soil/waste risers)", "pcs", 234, 2950.00, {"nrm": "8.1"}),
                ("F4.4", "Prefabricated bathroom pod (fully fitted, factory-installed)", "pcs", 120, 6800.00, {"nrm": "8.1"}),
                ("F4.5", "Mechanical ventilation heat-recovery (MVHR) unit per dwelling", "pcs", 120, 1850.00, {"nrm": "8.1"}),
                ("F4.6", "In-module ductwork & ceiling-void services", "m", 3500, 38.00, {"nrm": "8.1"}),
                ("F4.7", "Module inter-connection MEP termination plates (plug-and-play)", "pcs", 234, 620.00, {"nrm": "8.2"}),
                ("F4.8", "Fire detection & sounder first-fix (in-module, addressable)", "pcs", 234, 540.00, {"nrm": "8.4"}),
            ],
        ),
        # -- F5 Internal finishes (factory) ---------------------------------
        (
            "F5",
            "FACTORY - F5 Internal Finishes (factory)",
            {"nrm": "9"},
            [
                ("F5.1", "Internal partition linings & plasterboard (taped & jointed)", "m2", 14800, 31.00, {"nrm": "7.1"}),
                ("F5.2", "Wall & ceiling decoration (factory paint, 2 coats)", "m2", 22200, 9.50, {"nrm": "9.2"}),
                ("F5.3", "Floor finish - LVT to living / hall / kitchen", "m2", 4440, 38.00, {"nrm": "9.1"}),
                ("F5.4", "Floor finish - carpet to bedrooms", "m2", 2220, 26.00, {"nrm": "9.1"}),
                ("F5.5", "Fitted kitchen (units, worktop, integrated appliances) per dwelling", "pcs", 120, 5400.00, {"nrm": "9.3"}),
                ("F5.6", "Internal doors, ironmongery & architraves (per module)", "pcs", 234, 1250.00, {"nrm": "9.3"}),
                ("F5.7", "Skirtings, trims & second-fix joinery (per module)", "pcs", 234, 680.00, {"nrm": "9.3"}),
                ("F5.8", "Final clean, snag & module shrink-wrap protection", "pcs", 234, 420.00, {"nrm": "9.3"}),
            ],
        ),
        # -- F6 Factory testing & dispatch ----------------------------------
        (
            "F6",
            "FACTORY - F6 Pre-Dispatch Testing & Sign-off",
            {"nrm": "8"},
            [
                ("F6.1", "Module electrical test & certification (per module)", "pcs", 234, 320.00, {"nrm": "8.2"}),
                ("F6.2", "Module pressure / leak test plumbing (per module)", "pcs", 234, 240.00, {"nrm": "8.1"}),
                ("F6.3", "Air-tightness / acoustic spot test sampling (factory)", "pcs", 24, 1200.00, {"nrm": "8.1"}),
                ("F6.4", "Factory completion inspection & label (CSA A277 / ICC-MBI 1205)", "pcs", 234, 280.00, {"nrm": "0.4"}),
            ],
        ),
        # ===================================================================
        # SITE SCOPE  (enabling, foundations, install, weathering, stitch)
        # ===================================================================
        # -- S1 Site preliminaries & enabling -------------------------------
        (
            "S1",
            "SITE - S1 Enabling & Facilitating Works",
            {"nrm": "0"},
            [
                ("S1.1", "Site clearance & demolition of existing hardstanding", "m2", 4200, 18.00, {"nrm": "0.1"}),
                ("S1.2", "Ground investigation & contamination survey", "lsum", 1, 78000.00, {"nrm": "0.3"}),
                ("S1.3", "Site hoarding, welfare & temporary services", "month", 14, 9500.00, {"nrm": "0.1"}),
                ("S1.4", "Temporary haul road & crane hardstanding (granular, geogrid)", "m2", 1800, 46.00, {"nrm": "0.1"}),
                ("S1.5", "Statutory utility diversions & new connections", "lsum", 1, 165000.00, {"nrm": "0.2"}),
            ],
        ),
        # -- S2 Substructure & podium ---------------------------------------
        (
            "S2",
            "SITE - S2 Substructure & Transfer Podium",
            {"nrm": "1"},
            [
                ("S2.1", "CFA piling 600 mm to module grid", "m", 3600, 118.00, {"nrm": "1.1"}),
                ("S2.2", "Pile caps & ground beams (reinforced concrete)", "m3", 640, 315.00, {"nrm": "1.2"}),
                ("S2.3", "Transfer slab / podium deck 400 mm RC (module bearing)", "m2", 1250, 245.00, {"nrm": "1.3"}),
                ("S2.4", "Levelling base plates & shim packs to module corners", "pcs", 936, 145.00, {"nrm": "1.2"}),
                ("S2.5", "Below-podium tanking / waterproofing (Type A)", "m2", 1400, 82.00, {"nrm": "1.5"}),
                ("S2.6", "Ground-floor commercial / amenity slab & screed", "m2", 1100, 96.00, {"nrm": "1.3"}),
            ],
        ),
        # -- S3 Logistics, transport & craneage -----------------------------
        (
            "S3",
            "SITE - S3 Transport, Logistics & Craneage",
            {"nrm": "0"},
            [
                ("S3.1", "Abnormal-load module transport factory-to-site (per module)", "pcs", 234, 1450.00, {"nrm": "0.1"}),
                ("S3.2", "Escort, permits & route management (EU Directive 96/53/EC)", "lsum", 1, 96000.00, {"nrm": "0.1"}),
                ("S3.3", "Mobile crawler crane hire incl. operator (installation phase)", "month", 4, 114000.00, {"nrm": "0.1"}),
                ("S3.4", "Module lifting frames, spreader beams & rigging (EN 12811)", "lsum", 1, 58000.00, {"nrm": "0.1"}),
                ("S3.5", "Just-in-time module marshalling / holding yard", "month", 4, 22000.00, {"nrm": "0.1"}),
                ("S3.6", "Banksman, slinger & lift supervision team", "month", 4, 46000.00, {"nrm": "0.1"}),
            ],
        ),
        # -- S4 Module installation & inter-module connection ---------------
        (
            "S4",
            "SITE - S4 Module Installation & Inter-Module Connection",
            {"nrm": "2"},
            [
                ("S4.1", "Module set, plumb & align (craned lift + landing, per module)", "pcs", 234, 1850.00, {"nrm": "2.3"}),
                ("S4.2", "Inter-module structural connection (bolted, EN 1090-2 EXC2)", "pcs", 936, 285.00, {"nrm": "2.3"}),
                ("S4.3", "Vertical tie / disproportionate-collapse strapping", "pcs", 468, 165.00, {"nrm": "2.3"}),
                ("S4.4", "Site welding & local steel make-up (corridor / lift core tie-in)", "t", 95, 3850.00, {"nrm": "2.1"}),
                ("S4.5", "Lift & stair core (in-situ RC, site-built)", "m3", 320, 410.00, {"nrm": "2.1"}),
                ("S4.6", "Corridor / circulation infill decks between module lines", "m2", 1900, 88.00, {"nrm": "2.2"}),
            ],
        ),
        # -- S5 Weathering, roof & facade -----------------------------------
        (
            "S5",
            "SITE - S5 Weathering, Roof & Facade",
            {"nrm": "5"},
            [
                ("S5.1", "Inter-module joint weather-sealing & gasket make-good", "m", 4680, 28.00, {"nrm": "5.1"}),
                ("S5.2", "Rainscreen cladding system (A2-s1,d0, site-installed)", "m2", 8900, 245.00, {"nrm": "5.1"}),
                ("S5.3", "Cavity fire barriers & perimeter fire-stopping (site)", "m", 4680, 36.00, {"nrm": "5.1"}),
                ("S5.4", "Balconies / inset terraces (steel, site-bolted to modules)", "m2", 1450, 320.00, {"nrm": "3.2"}),
                ("S5.5", "Warm-roof build-up to top modules (single-ply + PIR 200 mm)", "m2", 1300, 138.00, {"nrm": "4.1"}),
                ("S5.6", "Parapet, copings & roof edge protection", "m", 480, 95.00, {"nrm": "4.1"}),
                ("S5.7", "PV array roof-mounted (incl. inverters, DC/AC)", "m2", 700, 210.00, {"nrm": "8.2"}),
            ],
        ),
        # -- S6 MEP stitching & central plant -------------------------------
        (
            "S6",
            "SITE - S6 MEP Stitching & Central Plant",
            {"nrm": "8"},
            [
                ("S6.1", "Riser stitching - connect module MEP to vertical risers", "pcs", 234, 680.00, {"nrm": "8.2"}),
                ("S6.2", "Central air-source heat-pump energy centre (cascade)", "lsum", 1, 420000.00, {"nrm": "8.1"}),
                ("S6.3", "Communal heat network distribution & HIUs per dwelling", "pcs", 120, 1650.00, {"nrm": "8.1"}),
                ("S6.4", "Incoming LV switchgear & landlord distribution", "lsum", 1, 185000.00, {"nrm": "8.2"}),
                ("S6.5", "Below-podium & external drainage connection", "m", 620, 128.00, {"nrm": "8.1"}),
                ("S6.6", "Lift installations (8-storey, MRL passenger)", "pcs", 3, 165000.00, {"nrm": "8.3"}),
                ("S6.7", "Landlord fire alarm, smoke control & sprinkler tie-in", "m2", 9250, 42.00, {"nrm": "8.4"}),
                ("S6.8", "Data / comms backbone & GPON to dwellings", "pcs", 120, 720.00, {"nrm": "8.2"}),
            ],
        ),
        # -- S7 External works ----------------------------------------------
        (
            "S7",
            "SITE - S7 External Works & Landscaping",
            {"nrm": "9"},
            [
                ("S7.1", "Hard landscaping - paving, podium courtyard", "m2", 1600, 105.00, {"nrm": "9.1"}),
                ("S7.2", "Soft landscaping, biodiverse roof & SuDS planting", "m2", 1200, 58.00, {"nrm": "9.2"}),
                ("S7.3", "Cycle store, bin store & substation enclosure", "lsum", 1, 145000.00, {"nrm": "9.1"}),
                ("S7.4", "External lighting, EV charge points & site services", "lsum", 1, 168000.00, {"nrm": "9.4"}),
                ("S7.5", "Boundary treatment, gates & access control", "m", 320, 165.00, {"nrm": "9.1"}),
            ],
        ),
        # -- S8 Testing, commissioning & handover ---------------------------
        (
            "S8",
            "SITE - S8 Testing, Commissioning & Handover",
            {"nrm": "8"},
            [
                ("S8.1", "Whole-building air-tightness testing (sample dwellings)", "pcs", 24, 850.00, {"nrm": "8.1"}),
                ("S8.2", "MEP commissioning, balancing & witnessing", "lsum", 1, 145000.00, {"nrm": "8.1"}),
                ("S8.3", "Acoustic pre-completion testing (Part E equivalent)", "pcs", 18, 1650.00, {"nrm": "8.1"}),
                ("S8.4", "Building Regs / regulatory completion (ICC-MBI 1205 alignment)", "lsum", 1, 64000.00, {"nrm": "0.4"}),
                ("S8.5", "O&M manuals, BIM as-built & soft-landings handover", "lsum", 1, 52000.00, {"nrm": "0.4"}),
                ("S8.6", "Post-completion defects retention works (allowance)", "lsum", 1, 85000.00, {"nrm": "0.4"}),
            ],
        ),
    ],
    markups=[
        ("Factory Overhead & Recovery", 12.0, "overhead", "direct_cost"),
        ("Site Preliminaries", 9.0, "overhead", "direct_cost"),
        ("Margin", 6.0, "profit", "direct_cost"),
        ("Design & Construction Contingency", 5.0, "contingency", "cumulative"),
    ],
    total_months=16,
    tender_name="Volumetric Module Supply & Install Package",
    tender_companies=[
        ("Modulark Systems", "tenders@modulark.example", 0.98),
        ("Falkbeck GmbH (Modular)", "angebote@falkbeck.example", 1.04),
        ("Rijnhout Modulair B.V.", "tender@rijnhout.example", 0.99),
        ("Elmcastle Communities Ltd", "bids@elmcastle.example", 1.06),
        ("Larvex / Modulon", "offsite@larvex.example", 1.02),
    ],
    project_metadata={
        "address": "NDSM Wharf, Amsterdam-Noord",
        "client": "Riverside Living Cooperative",
        "architect": "Kallenberg Architecten / Offsite Studio",
        "gia_m2": 9250,
        "treated_floor_area_m2": 7400,
        "units": 120,
        "modules": 234,
        "storeys": 8,
        "structure_system": "Light-gauge steel volumetric modules on RC transfer podium",
        "mmc_category": "Category 1 (3D primary structural)",
        "offsite_value_pct": 65,
        "energy_class": "EPC A / nZEB",
        "fabric_target": "U-value walls ≤ 0.18, windows Uw ≤ 0.9, air-tightness ≤ 1.0",
        "standards": [
            "EN 1090-2 (EXC2) steel execution",
            "EN 1993 / EN 1995 structural design",
            "ICC/MBI 1200 off-site planning & inspection",
            "ICC/MBI 1205 off-site construction inspection & regulatory compliance",
            "CSA A277 certification of factory-built buildings",
            "EN 12811 temporary works for craneage",
            "EU Directive 96/53/EC abnormal-load transport",
        ],
        "regulator": "Gemeente Amsterdam (omgevingsvergunning) + notified body for EN 1090 FPC",
        "permit_notes": (
            "Omgevingsvergunning (environmental/building permit) required; factory "
            "certification (FPC) audited by EN 1090 notified body; module type "
            "approval evidenced per ICC/MBI 1200 prior to manufacture."
        ),
        "sustainability": "nZEB, biodiverse roof + SuDS, roof PV, communal ASHP heat network",
        "procurement": "Two-stage Design & Build with named modular trade contractor",
    },
)
