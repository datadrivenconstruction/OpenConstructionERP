# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: Mixed-use residential-over-retail, Sydney NSW
#
# Australian elemental cost plan (AIQS / NRM elemental method). 9-storey
# reinforced-concrete development at Green Square, ~10,500 m2 GFA, 94
# apartments over two retail tenancies and a two-level basement car park.
# Compliant with NCC 2022, AS 3600 (concrete), AS 4100 (structural steel),
# AS 1684 (timber), AS 1428.1 (access). Price level: Sydney Q1 2026.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="mixed-use-sydney",
    project_name="Green Square Quarter - Mixed-Use Development",
    project_description=(
        "New 9-storey mixed-use development at Green Square, Sydney. Two "
        "ground-floor retail tenancies and a residential lobby over 8 upper "
        "residential levels comprising 94 apartments (a mix of 1, 2 and 3 "
        "bedroom). Two-level basement car park with 96 spaces plus bicycle "
        "and EV charging. Reinforced-concrete frame with band-beam and "
        "post-tensioned suspended slabs to AS 3600, structural steel canopy "
        "to AS 4100. Site area approx. 2,650 m2, gross floor area approx. "
        "10,500 m2. Designed to NCC 2022 (NatHERS 7-star average, BASIX), "
        "Green Star Buildings 5-Star target, AS 1428.1 accessible. "
        "Estimated construction cost approx. AUD 51M."
    ),
    region="AU",
    classification_standard="nrm",
    currency="AUD",
    locale="en-AU",
    address={
        "street": "8 Joynton Avenue, Zetland",
        "city": "Sydney",
        "postcode": "NSW 2017",
        "country": "Australia",
        "lat": -33.9069,
        "lng": 151.2056,
    },
    validation_rule_sets=["nrm", "boq_quality"],
    boq_name="Elemental Cost Plan - AIQS / NRM Elemental",
    boq_description=(
        "Elemental cost plan prepared on the Australian elemental method "
        "(AIQS), aligned to NRM elemental groups, Sydney Q1 2026 rates."
    ),
    boq_metadata={
        "standard": "AIQS Australian Cost Management Manual / NRM 1 elemental",
        "phase": "Design Development cost plan (Stage C)",
        "base_date": "2026-Q1",
        "price_level": "Sydney 2026",
        "tender_price_index_nsw": 128,
    },
    sections=[
        # ── Preliminaries ────────────────────────────────────────────────
        (
            "0",
            "0 - Preliminaries (Site establishment & management)",
            {"nrm": "0"},
            [
                ("0.1", "Site establishment, sheds & amenities (Site setup)", "lsum", 1, 420000.00, {"nrm": "0.1"}),
                ("0.2", "Tower crane hire & erection (Crane)", "month", 16, 38000.00, {"nrm": "0.2"}),
                ("0.3", "Materials & passenger hoist (Hoist)", "month", 12, 14500.00, {"nrm": "0.3"}),
                ("0.4", "Perimeter hoarding & site fencing (Hoarding)", "m", 210, 185.00, {"nrm": "0.4"}),
                ("0.5", "Temporary power, water & telecoms (Temp services)", "lsum", 1, 165000.00, {"nrm": "0.5"}),
                ("0.6", "Site management & supervision staff (Site staff)", "month", 18, 62000.00, {"nrm": "0.6"}),
                ("0.7", "Work health & safety, traffic control (WHS)", "lsum", 1, 285000.00, {"nrm": "0.7"}),
                ("0.8", "Survey, set-out & dilapidation reports (Survey)", "lsum", 1, 95000.00, {"nrm": "0.8"}),
                ("0.9", "Progressive & final clean (Cleaning)", "lsum", 1, 145000.00, {"nrm": "0.9"}),
            ],
        ),
        # ── Substructure ─────────────────────────────────────────────────
        (
            "1",
            "1 - Substructure (Foundations & basement)",
            {"nrm": "1"},
            [
                ("1.1", "Bulk excavation basement, rock to spoil (Bulk dig)", "m3", 22000, 58.00, {"nrm": "1.1"}),
                ("1.2", "Contiguous bored pier shoring wall (Shoring)", "m2", 3200, 285.00, {"nrm": "1.2"}),
                ("1.3", "Rock anchors & soil nails (Anchors)", "pcs", 180, 1450.00, {"nrm": "1.3"}),
                ("1.4", "Bored cast-in-situ piers 900mm to AS 3600 (Piers)", "m", 880, 365.00, {"nrm": "1.4"}),
                ("1.5", "Pile caps & ground beams N40 (Pile caps)", "m3", 420, 520.00, {"nrm": "1.5"}),
                ("1.6", "Ground slab 200mm on ground, vapour barrier (Slab on ground)", "m2", 2400, 165.00, {"nrm": "1.6"}),
                ("1.7", "Basement retaining walls 300mm RC (Basement walls)", "m2", 3600, 245.00, {"nrm": "1.7"}),
                ("1.8", "Tanking & waterproof membrane to basement (Tanking)", "m2", 5800, 92.00, {"nrm": "1.8"}),
                ("1.9", "Sub-soil drainage & agg drains (Subsoil drainage)", "m", 640, 78.00, {"nrm": "1.9"}),
                ("1.10", "Termite management system AS 3660 (Termite barrier)", "m2", 2400, 18.50, {"nrm": "1.10"}),
            ],
        ),
        # ── Columns ──────────────────────────────────────────────────────
        (
            "2.1",
            "2.1 - Columns (Vertical structure)",
            {"nrm": "2.1"},
            [
                ("2.1.1", "RC columns 600x600 N50 basement/podium (Columns lower)", "m3", 320, 685.00, {"nrm": "2.1"}),
                ("2.1.2", "RC columns 450x450 N40 typical (Columns upper)", "m3", 410, 640.00, {"nrm": "2.1"}),
                ("2.1.3", "Reinforcement to columns 500MPa (Column rebar)", "t", 165, 3650.00, {"nrm": "2.1"}),
                ("2.1.4", "Column formwork & propping (Column forms)", "m2", 4200, 95.00, {"nrm": "2.1"}),
            ],
        ),
        # ── Upper floors ─────────────────────────────────────────────────
        (
            "2.2",
            "2.2 - Upper Floors (Suspended slabs & beams)",
            {"nrm": "2.2"},
            [
                ("2.2.1", "Post-tensioned suspended slab 220mm N40 (PT slabs)", "m2", 9600, 215.00, {"nrm": "2.2"}),
                ("2.2.2", "Band beams to AS 3600 (Band beams)", "m3", 680, 580.00, {"nrm": "2.2"}),
                ("2.2.3", "Reinforcement to slabs & beams 500MPa (Slab rebar)", "t", 540, 3550.00, {"nrm": "2.2"}),
                ("2.2.4", "Post-tensioning strand & anchorages (PT strand)", "t", 58, 7200.00, {"nrm": "2.2"}),
                ("2.2.5", "Suspended slab soffit formwork (Slab forms)", "m2", 9600, 78.00, {"nrm": "2.2"}),
                ("2.2.6", "Transfer slab 800mm over podium (Transfer slab)", "m3", 480, 720.00, {"nrm": "2.2"}),
            ],
        ),
        # ── Staircases & lift cores ──────────────────────────────────────
        (
            "2.3",
            "2.3 - Staircases & Lift Cores (Vertical access structure)",
            {"nrm": "2.3"},
            [
                ("2.3.1", "RC lift & stair core walls 250mm (Core walls)", "m3", 520, 615.00, {"nrm": "2.3"}),
                ("2.3.2", "Precast concrete stair flights (Stairs)", "pcs", 36, 4800.00, {"nrm": "2.3"}),
                ("2.3.3", "Reinforcement to cores 500MPa (Core rebar)", "t", 92, 3600.00, {"nrm": "2.3"}),
                ("2.3.4", "Galvanised steel balustrade to stairs AS 1657 (Balustrade)", "m", 420, 320.00, {"nrm": "2.3"}),
            ],
        ),
        # ── Roof ─────────────────────────────────────────────────────────
        (
            "2.4",
            "2.4 - Roof (Roof structure & coverings)",
            {"nrm": "2.4"},
            [
                ("2.4.1", "Concrete roof slab 200mm with falls (Roof slab)", "m2", 1400, 195.00, {"nrm": "2.4"}),
                ("2.4.2", "Roof membrane, torch-on 2-ply (Waterproofing)", "m2", 1400, 88.00, {"nrm": "2.4"}),
                ("2.4.3", "Insulation R4.0 & protection board (Roof insulation)", "m2", 1400, 52.00, {"nrm": "2.4"}),
                ("2.4.4", "Paver pedestal system to communal terrace (Pavers)", "m2", 480, 165.00, {"nrm": "2.4"}),
                ("2.4.5", "Roof plant screen, perforated metal (Plant screen)", "m2", 320, 285.00, {"nrm": "2.4"}),
                ("2.4.6", "Box gutters, rainheads & downpipes (Roof drainage)", "m", 240, 145.00, {"nrm": "2.4"}),
            ],
        ),
        # ── External walls, windows & doors ──────────────────────────────
        (
            "2.5",
            "2.5 - External Walls, Windows & Doors (Facade)",
            {"nrm": "2.5"},
            [
                ("2.5.1", "Precast concrete facade panels, finished (Precast facade)", "m2", 3200, 425.00, {"nrm": "2.5"}),
                ("2.5.2", "Aluminium-framed window wall, double glazed (Window wall)", "m2", 2800, 685.00, {"nrm": "2.5"}),
                ("2.5.3", "Sliding glazed balcony doors AS 2047 (Balcony doors)", "m2", 940, 720.00, {"nrm": "2.5"}),
                ("2.5.4", "Retail shopfront glazing, structural (Shopfront)", "m2", 360, 950.00, {"nrm": "2.5"}),
                ("2.5.5", "Lightweight render facade system, EIFS (Render facade)", "m2", 1600, 285.00, {"nrm": "2.5"}),
                ("2.5.6", "Aluminium balustrade & glazed balcony screens (Balcony balustrade)", "m", 880, 380.00, {"nrm": "2.5"}),
                ("2.5.7", "External applied finishes & sealants (Facade sealants)", "m", 1200, 42.00, {"nrm": "2.5"}),
            ],
        ),
        # ── Internal walls & partitions ──────────────────────────────────
        (
            "2.6",
            "2.6 - Internal Walls & Partitions",
            {"nrm": "2.6"},
            [
                ("2.6.1", "Inter-tenancy fire/acoustic wall, Rw60 (Party walls)", "m2", 6400, 165.00, {"nrm": "2.6"}),
                ("2.6.2", "Apartment internal stud partitions (Internal walls)", "m2", 9800, 95.00, {"nrm": "2.6"}),
                ("2.6.3", "Wet-area lining, fibre-cement & waterproofing (Wet wall lining)", "m2", 3600, 115.00, {"nrm": "2.6"}),
                ("2.6.4", "Shaft & riser fire-rated walls (Shaft walls)", "m2", 1800, 135.00, {"nrm": "2.6"}),
                ("2.6.5", "Solid-core entry doors, fire-rated FRL 60/60/60 (Entry doors)", "pcs", 94, 1250.00, {"nrm": "2.6"}),
                ("2.6.6", "Internal apartment doors, hung & hardware (Internal doors)", "pcs", 470, 520.00, {"nrm": "2.6"}),
            ],
        ),
        # ── Internal finishes ────────────────────────────────────────────
        (
            "3",
            "3 - Internal Finishes (Floor, wall & ceiling finishes)",
            {"nrm": "3"},
            [
                ("3.1", "Engineered timber flooring, living areas (Timber floor)", "m2", 5400, 145.00, {"nrm": "3.1"}),
                ("3.2", "Porcelain floor tiling, wet areas & retail (Floor tiling)", "m2", 3200, 135.00, {"nrm": "3.2"}),
                ("3.3", "Carpet to bedrooms, commercial grade (Carpet)", "m2", 3600, 78.00, {"nrm": "3.3"}),
                ("3.4", "Wall tiling to bathrooms & kitchens (Wall tiling)", "m2", 4200, 115.00, {"nrm": "3.4"}),
                ("3.5", "Plasterboard ceiling lining & cornice (Ceilings)", "m2", 9200, 62.00, {"nrm": "3.5"}),
                ("3.6", "Suspended acoustic ceiling, lobby & retail (Acoustic ceiling)", "m2", 1400, 95.00, {"nrm": "3.6"}),
                ("3.7", "Paint to walls & ceilings, low-VOC (Painting)", "m2", 28000, 24.00, {"nrm": "3.7"}),
                ("3.8", "Skirting, architraves & timber trims (Joinery trims)", "m", 9600, 22.00, {"nrm": "3.8"}),
                ("3.9", "Polished concrete to basement & retail (Polished concrete)", "m2", 2200, 58.00, {"nrm": "3.9"}),
            ],
        ),
        # ── Fittings & fixtures ──────────────────────────────────────────
        (
            "4",
            "4 - Fittings, Furnishings & Equipment",
            {"nrm": "4"},
            [
                ("4.1", "Kitchen joinery & benchtops, stone (Kitchens)", "pcs", 94, 14500.00, {"nrm": "4.1"}),
                ("4.2", "Bathroom & ensuite vanity joinery (Vanities)", "pcs", 168, 3800.00, {"nrm": "4.2"}),
                ("4.3", "Built-in robes & wardrobe joinery (Robes)", "pcs", 220, 1850.00, {"nrm": "4.3"}),
                ("4.4", "Kitchen appliances, integrated (Appliances)", "pcs", 94, 6200.00, {"nrm": "4.4"}),
                ("4.5", "Mirrors, shelving & bathroom accessories (Accessories)", "pcs", 168, 720.00, {"nrm": "4.5"}),
                ("4.6", "Lobby & common-area FF&E, signage (Common FF&E)", "lsum", 1, 285000.00, {"nrm": "4.6"}),
                ("4.7", "Letterboxes, bin store & parcel lockers (Mail & bins)", "lsum", 1, 78000.00, {"nrm": "4.7"}),
            ],
        ),
        # ── Hydraulic services ───────────────────────────────────────────
        (
            "5.1",
            "5.1 - Services: Hydraulic (Plumbing & drainage)",
            {"nrm": "5.1"},
            [
                ("5.1.1", "Cold & hot water reticulation, copper/PEX (Water reticulation)", "m", 4800, 58.00, {"nrm": "5.1"}),
                ("5.1.2", "Sanitary drainage uPVC DN100/150 (Sanitary drainage)", "m", 2600, 72.00, {"nrm": "5.1"}),
                ("5.1.3", "Stormwater drainage & detention tank (Stormwater)", "lsum", 1, 245000.00, {"nrm": "5.1"}),
                ("5.1.4", "Sanitary fixtures & tapware per apartment (Fixtures)", "pcs", 94, 4200.00, {"nrm": "5.1"}),
                ("5.1.5", "Central gas hot-water plant & flues (HW plant)", "lsum", 1, 165000.00, {"nrm": "5.1"}),
                ("5.1.6", "Natural gas reticulation & meters (Gas)", "m", 620, 65.00, {"nrm": "5.1"}),
                ("5.1.7", "Rainwater harvesting & reuse pumps (Rainwater reuse)", "lsum", 1, 95000.00, {"nrm": "5.1"}),
            ],
        ),
        # ── Mechanical services ──────────────────────────────────────────
        (
            "5.2",
            "5.2 - Services: Mechanical (HVAC & ventilation)",
            {"nrm": "5.2"},
            [
                ("5.2.1", "Split-system air conditioning per apartment (Split AC)", "pcs", 94, 5800.00, {"nrm": "5.2"}),
                ("5.2.2", "Bathroom & laundry exhaust ventilation (Exhaust fans)", "pcs", 262, 320.00, {"nrm": "5.2"}),
                ("5.2.3", "Basement car-park jet-fan ventilation (Carpark vent)", "lsum", 1, 385000.00, {"nrm": "5.2"}),
                ("5.2.4", "Retail tenancy mechanical provision (Retail HVAC)", "m2", 720, 185.00, {"nrm": "5.2"}),
                ("5.2.5", "Common-area & corridor ventilation (Corridor vent)", "m", 1200, 95.00, {"nrm": "5.2"}),
                ("5.2.6", "Mechanical controls & BMS interface (Mech controls)", "lsum", 1, 145000.00, {"nrm": "5.2"}),
            ],
        ),
        # ── Electrical services ──────────────────────────────────────────
        (
            "5.3",
            "5.3 - Services: Electrical (Power, lighting & comms)",
            {"nrm": "5.3"},
            [
                ("5.3.1", "Main switchboard & sub-mains, Ausgrid (Switchboards)", "lsum", 1, 420000.00, {"nrm": "5.3"}),
                ("5.3.2", "Apartment power & lighting reticulation (Apt electrical)", "pcs", 94, 6800.00, {"nrm": "5.3"}),
                ("5.3.3", "LED light fittings, apartments & common (Light fittings)", "pcs", 2800, 95.00, {"nrm": "5.3"}),
                ("5.3.4", "Communications, NBN & data cabling (Comms cabling)", "m", 6200, 18.00, {"nrm": "5.3"}),
                ("5.3.5", "Rooftop solar PV array 60kW & inverters (Solar PV)", "lsum", 1, 138000.00, {"nrm": "5.3"}),
                ("5.3.6", "EV charging infrastructure, basement (EV charging)", "pcs", 24, 3200.00, {"nrm": "5.3"}),
                ("5.3.7", "Security, CCTV & access control (Security)", "lsum", 1, 225000.00, {"nrm": "5.3"}),
                ("5.3.8", "Lightning protection & earthing AS 1768 (Earthing)", "lsum", 1, 68000.00, {"nrm": "5.3"}),
            ],
        ),
        # ── Fire services ────────────────────────────────────────────────
        (
            "5.4",
            "5.4 - Services: Fire (Protection & detection)",
            {"nrm": "5.4"},
            [
                ("5.4.1", "Sprinkler system to AS 2118, full coverage (Sprinklers)", "m2", 10500, 38.00, {"nrm": "5.4"}),
                ("5.4.2", "Fire hydrants & hose reels AS 2419 (Hydrants)", "lsum", 1, 185000.00, {"nrm": "5.4"}),
                ("5.4.3", "Fire detection & alarm, addressable AS 1670 (Fire alarm)", "m2", 10500, 22.00, {"nrm": "5.4"}),
                ("5.4.4", "Fire pump set & on-site water tank (Fire pumps)", "pcs", 1, 145000.00, {"nrm": "5.4"}),
                ("5.4.5", "Stair pressurisation & smoke exhaust (Smoke control)", "lsum", 1, 165000.00, {"nrm": "5.4"}),
            ],
        ),
        # ── Lift / vertical transport ────────────────────────────────────
        (
            "5.5",
            "5.5 - Services: Lift Installations (Vertical transport)",
            {"nrm": "5.5"},
            [
                ("5.5.1", "Passenger lifts 13-person, 11 stops MRL (Passenger lifts)", "pcs", 3, 245000.00, {"nrm": "5.5"}),
                ("5.5.2", "Goods/accessible lift 21-person (Goods lift)", "pcs", 1, 320000.00, {"nrm": "5.5"}),
                ("5.5.3", "Lift shaft fit-out & builders work (Lift BW)", "lsum", 1, 95000.00, {"nrm": "5.5"}),
            ],
        ),
        # ── External & site works ────────────────────────────────────────
        (
            "6",
            "6 - External & Site Works (Landscape & infrastructure)",
            {"nrm": "6"},
            [
                ("6.1", "Site demolition & clearance (Demolition)", "lsum", 1, 185000.00, {"nrm": "6.1"}),
                ("6.2", "Basement car-park line marking & equipment (Carpark fitout)", "m2", 4800, 48.00, {"nrm": "6.2"}),
                ("6.3", "Hard landscape, paving & kerbing (Hardscape)", "m2", 1600, 165.00, {"nrm": "6.3"}),
                ("6.4", "Soft landscape, planting & irrigation (Softscape)", "m2", 900, 95.00, {"nrm": "6.4"}),
                ("6.5", "Communal podium garden & terrace (Podium garden)", "m2", 620, 285.00, {"nrm": "6.5"}),
                ("6.6", "Site services connections, Sydney Water/Ausgrid (Authority connections)", "lsum", 1, 380000.00, {"nrm": "6.6"}),
                ("6.7", "Boundary fencing, gates & bin enclosure (Fencing)", "m", 180, 285.00, {"nrm": "6.7"}),
                ("6.8", "External lighting & signage (Site lighting)", "lsum", 1, 125000.00, {"nrm": "6.8"}),
            ],
        ),
    ],
    markups=[
        ("Builder's Preliminaries", 9.5, "overhead", "direct_cost"),
        ("Design & Construction Contingency", 5.0, "contingency", "direct_cost"),
        ("Builder's Margin (Overheads & Profit)", 6.0, "profit", "cumulative"),
    ],
    total_months=20,
    tender_name="Structure & Facade Trade Package",
    tender_companies=[
        ("Alwyn Perrick Constructions", "tenders@perrick.example", 0.98),
        ("Formara Pty Ltd", "estimating@formara.example", 1.05),
        ("Kenbarrow Builders", "tenders@kenbarrow.example", 1.01),
    ],
    tender_packages=[
        (
            "Structure & Facade Trade Package",
            "Substructure, RC frame, post-tensioned slabs, precast & glazed facade",
            "evaluating",
            [
                ("Alwyn Perrick Constructions", "tenders@perrick.example", 0.98),
                ("Formara Pty Ltd", "estimating@formara.example", 1.05),
                ("Kenbarrow Builders", "tenders@kenbarrow.example", 1.01),
            ],
        ),
        (
            "Building Services (MEP) Package",
            "Hydraulic, mechanical, electrical, fire and lift installations",
            "evaluating",
            [
                ("R.T. Halligan Group", "tenders@halligan.example", 0.99),
                ("Wexlon Group", "estimating@wexlon.example", 1.04),
                ("Kelverne Australia", "tenders@kelverne.example", 1.02),
            ],
        ),
        (
            "Fitout & Finishes Package",
            "Internal partitions, finishes, joinery, kitchens and bathrooms",
            "evaluating",
            [
                ("Marrowvale Construction & Fitout", "tenders@marrowvale.example", 0.97),
                ("SPANE Australia", "estimating@spane.example", 1.06),
                ("Craftmoor Group", "tenders@craftmoor.example", 1.03),
            ],
        ),
    ],
    project_metadata={
        "address": "8 Joynton Avenue, Zetland (Green Square), Sydney NSW 2017",
        "client": "Harbourmill Quarter Development Pty Ltd",
        "architect": "Verrow Kelsey",
        "quantity_surveyor": "Cranleigh Partnership (AIQS)",
        "structural_engineer": "Kelso Brannagh Vint",
        "gfa_m2": 10500,
        "site_area_m2": 2650,
        "storeys": 9,
        "basement_levels": 2,
        "apartments": 94,
        "car_spaces": 96,
        "construction_standards": [
            "NCC 2022 (Building Code of Australia)",
            "AS 3600 Concrete structures",
            "AS 4100 Steel structures",
            "AS 1684 Residential timber framing",
            "AS 1428.1 Access and mobility",
            "AS 2118 Automatic fire sprinkler systems",
            "AS 1670 Fire detection, warning & control",
        ],
        "regulator": "City of Sydney Council / NSW DPE (SSD pathway)",
        "permit_notes": (
            "Construction certificate under EP&A Act 1979; BASIX certificate "
            "and Section J (NCC 2022) energy compliance lodged."
        ),
        "sustainability": "Green Star Buildings 5-Star target; NatHERS 7-star average; rooftop 60kW solar PV",
        "procurement": "Design & Construct (lump sum)",
    },
)
