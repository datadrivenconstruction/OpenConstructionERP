# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Flagship demo: Hyperscale data centre, Melbourne VIC (west industrial)
#
# Mission-critical hyperscale facility in the Truganina / west Melbourne
# industrial precinct. 30 MW critical IT load delivered across four data
# halls, designed to Uptime Institute Tier III (concurrently maintainable)
# with N+1 redundancy on power and cooling. Single-storey tilt-up / precast
# concrete shell with a structural-steel roof over the white space, two-storey
# administration and electrical/mechanical plant blocks. Gross building area
# approx. 18,400 m2 on a 4.2 ha site. Compliant with NCC 2022, AS 3600
# (concrete), AS 4100 (structural steel), AS 1170 (structural actions),
# AS 1668 (mechanical ventilation), AS 2118 / ISO 14520 (fire), and the
# data-centre infrastructure standard AS/NZS / ANSI-TIA-942 reference.
# Price level: Melbourne Q1 2026. Estimated construction cost approx.
# AUD 285M direct, prepared on the Australian elemental method (AIQS / NRM 1
# elemental). Procurement: Design & Construct, lump sum.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="data-center-melbourne",
    project_name="Hyperscale Data Centre - Melbourne West (MEL01)",
    project_description=(
        "New hyperscale data centre in the Truganina industrial precinct, "
        "west Melbourne. Single building of approx. 18,400 m2 delivering 30 MW "
        "of critical IT load across four data halls, plus two-storey "
        "administration, network operations and back-of-house plant. Designed "
        "to Uptime Institute Tier III (concurrently maintainable) with N+1 "
        "redundancy on electrical and mechanical infrastructure: dedicated HV "
        "intake and zone substation, 11 kV / 415 V transformers, switchgear, "
        "static UPS with battery autonomy, and standby diesel generators with "
        "bulk fuel storage. Cooling by N+1 air-cooled chillers, chilled-water "
        "reticulation and in-row / CRAC units serving hot-aisle containment "
        "white space on a raised access floor. Tilt-up / precast concrete shell "
        "with a long-span structural-steel roof to AS 4100, ground slab and "
        "plinths to AS 3600. Fire protection by gaseous (inert-gas) suppression "
        "and VESDA aspirating detection to the data halls, with sprinklers to "
        "back-of-house. Compliant with NCC 2022, AS 1170, AS 1668, AS 2118 and "
        "ANSI/TIA-942 data-centre infrastructure reference. PUE design target "
        "1.3. Site area approx. 4.2 ha. Estimated construction cost approx. "
        "AUD 285M direct (Melbourne Q1 2026, ex GST)."
    ),
    region="AU",
    classification_standard="nrm",
    currency="AUD",
    locale="en-AU",
    address={
        "street": "120 Doherty's Road, Truganina",
        "city": "Melbourne",
        "postcode": "VIC 3029",
        "country": "Australia",
        "lat": -37.8136,
        "lng": 144.7389,
    },
    validation_rule_sets=["nrm", "boq_quality"],
    boq_name="Elemental Cost Plan - AIQS / NRM Elemental",
    boq_description=(
        "Elemental cost plan prepared on the Australian elemental method "
        "(AIQS), aligned to NRM 1 elemental groups, Melbourne Q1 2026 rates. "
        "Critical IT load 30 MW, Tier III, N+1. Direct costs in AUD, ex GST."
    ),
    boq_metadata={
        "standard": "AIQS Australian Cost Management Manual / NRM 1 elemental",
        "phase": "Design Development cost plan (Stage C)",
        "base_date": "2026-Q1",
        "price_level": "Melbourne 2026",
        "tender_price_index_vic": 124,
        "critical_it_load_mw": 30,
        "tier": "Uptime Institute Tier III",
        "redundancy": "N+1",
        "pue_target": 1.3,
    },
    sections=[
        # ── Preliminaries ────────────────────────────────────────────────
        (
            "0",
            "0 - Preliminaries (Site establishment & management)",
            {"nrm": "0"},
            [
                ("0.1", "Site establishment, compound, sheds & amenities (Site setup)", "lsum", 1, 2850000.00, {"nrm": "0.1"}),
                ("0.2", "Crawler & mobile cranage, steel erection plant (Cranage)", "month", 22, 96000.00, {"nrm": "0.2"}),
                ("0.3", "Perimeter hoarding, security fencing & gatehouse (Hoarding)", "m", 920, 220.00, {"nrm": "0.3"}),
                ("0.4", "Temporary power, water & telecoms (Temp services)", "lsum", 1, 685000.00, {"nrm": "0.4"}),
                ("0.5", "Project & construction management staff (Site staff)", "month", 26, 145000.00, {"nrm": "0.5"}),
                ("0.6", "Work health & safety, traffic management (WHS)", "lsum", 1, 1250000.00, {"nrm": "0.6"}),
                ("0.7", "Survey, set-out, monitoring & dilapidation (Survey)", "lsum", 1, 285000.00, {"nrm": "0.7"}),
                ("0.8", "Integrated commissioning management (Cx mgmt)", "lsum", 1, 1850000.00, {"nrm": "0.8"}),
                ("0.9", "Progressive & final clean, white-space fit clean (Cleaning)", "lsum", 1, 420000.00, {"nrm": "0.9"}),
                ("0.10", "Environmental controls, dust & sediment (Environmental)", "lsum", 1, 365000.00, {"nrm": "0.10"}),
            ],
        ),
        # ── Bulk earthworks & substructure ───────────────────────────────
        (
            "1",
            "1 - Substructure (Bulk earthworks, foundations & slab)",
            {"nrm": "1"},
            [
                ("1.1", "Site clearing, strip topsoil & grub (Site clearing)", "m2", 42000, 6.50, {"nrm": "1.1"}),
                ("1.2", "Bulk earthworks cut to fill, basaltic ground (Bulk earthworks)", "m3", 96000, 28.00, {"nrm": "1.1"}),
                ("1.3", "Detailed excavation to footings & pits (Detailed excavation)", "m3", 14500, 52.00, {"nrm": "1.1"}),
                ("1.4", "Engineered structural fill & compaction (Engineered fill)", "m3", 38000, 42.00, {"nrm": "1.1"}),
                ("1.5", "Capping layer & subgrade improvement (Subgrade prep)", "m2", 22000, 38.00, {"nrm": "1.1"}),
                ("1.6", "Bored cast-in-situ piers 750mm to AS 3600 (Piers)", "m", 4200, 345.00, {"nrm": "1.2"}),
                ("1.7", "Pad & strip footings N32 reinforced (Footings)", "m3", 2400, 510.00, {"nrm": "1.2"}),
                ("1.8", "Ground slab 250mm post-tensioned, vapour barrier (Ground slab)", "m2", 16800, 185.00, {"nrm": "1.2"}),
                ("1.9", "Reinforcement & PT strand to substructure (Substructure rebar)", "t", 1850, 3450.00, {"nrm": "1.2"}),
                ("1.10", "Equipment plinths & generator/transformer pads (Equipment plinths)", "m3", 980, 620.00, {"nrm": "1.2"}),
                ("1.11", "In-ground services trenches & duct banks (Duct banks)", "m", 3600, 285.00, {"nrm": "1.2"}),
                ("1.12", "Sub-soil drainage & agg drains (Subsoil drainage)", "m", 2400, 78.00, {"nrm": "1.1"}),
            ],
        ),
        # ── Frame: precast / tilt-up & structural steel ──────────────────
        (
            "2.1",
            "2.1 - Frame (Precast/tilt-up shell & structural steel)",
            {"nrm": "2.1"},
            [
                ("2.1.1", "Tilt-up concrete wall panels, cast & erect (Tilt-up panels)", "m2", 14200, 285.00, {"nrm": "2.1"}),
                ("2.1.2", "Precast concrete columns & spandrels (Precast columns)", "m3", 720, 1450.00, {"nrm": "2.1"}),
                ("2.1.3", "Structural steel roof framing, long-span to AS 4100 (Steel roof frame)", "t", 1650, 5400.00, {"nrm": "2.1"}),
                ("2.1.4", "Structural steel to plant platforms & mezzanines (Steel platforms)", "t", 420, 5800.00, {"nrm": "2.1"}),
                ("2.1.5", "Steel roof purlins & bracing (Purlins/bracing)", "t", 380, 4600.00, {"nrm": "2.1"}),
                ("2.1.6", "Composite steel deck & topping, admin floor (Composite deck)", "m2", 2200, 165.00, {"nrm": "2.1"}),
                ("2.1.7", "Panel connections, grout & temporary propping (Panel connections)", "pcs", 540, 1850.00, {"nrm": "2.1"}),
                ("2.1.8", "Protective coatings & galvanising to steel (Steel coatings)", "t", 2450, 980.00, {"nrm": "2.1"}),
                ("2.1.9", "Passive fire protection to steel, FRL (Steel fireproofing)", "m2", 9800, 78.00, {"nrm": "2.1"}),
            ],
        ),
        # ── Roof & external cladding ─────────────────────────────────────
        (
            "2.4",
            "2.4 - Roof & External Cladding (Envelope)",
            {"nrm": "2.4"},
            [
                ("2.4.1", "Insulated metal roof sheeting, Kliplok concealed-fix (Roof sheeting)", "m2", 17200, 145.00, {"nrm": "2.4"}),
                ("2.4.2", "Roof insulation & anticon blanket R4.0 (Roof insulation)", "m2", 17200, 38.00, {"nrm": "2.4"}),
                ("2.4.3", "Architectural metal wall cladding to admin & screens (Wall cladding)", "m2", 4800, 215.00, {"nrm": "2.4"}),
                ("2.4.4", "Box gutters, rainheads, sumps & downpipes (Roof drainage)", "m", 1400, 165.00, {"nrm": "2.4"}),
                ("2.4.5", "Roof safety, walkways, mansafe & plant screens (Roof safety)", "m2", 2200, 185.00, {"nrm": "2.4"}),
                ("2.4.6", "Aluminium curtain wall & glazing to admin entry (Curtain wall)", "m2", 980, 720.00, {"nrm": "2.4"}),
                ("2.4.7", "Louvre intake/exhaust screens to plant (Acoustic louvres)", "m2", 1650, 385.00, {"nrm": "2.4"}),
                ("2.4.8", "External sealants, flashings & waterproofing (Envelope sealants)", "m", 3200, 48.00, {"nrm": "2.4"}),
            ],
        ),
        # ── White-space fit-out (data halls) ─────────────────────────────
        (
            "3",
            "3 - White Space Fit-out (Data halls & internal finishes)",
            {"nrm": "3"},
            [
                ("3.1", "Raised access floor 1200mm, 12 kN/m2, data halls (Raised floor)", "m2", 6400, 285.00, {"nrm": "3.1"}),
                ("3.2", "Hot-aisle containment systems, doors & roofs (Containment)", "m", 1850, 1450.00, {"nrm": "3.2"}),
                ("3.3", "Overhead busway support & cable basket grid (Cable management)", "m", 4200, 165.00, {"nrm": "3.3"}),
                ("3.4", "Data-hall partition walls, fire-rated FRL 120/120/120 (Fire walls)", "m2", 3800, 195.00, {"nrm": "3.4"}),
                ("3.5", "Sealed vapour-tight ceiling to data halls (Sealed ceiling)", "m2", 6400, 115.00, {"nrm": "3.5"}),
                ("3.6", "Sealed epoxy floor coating beneath raised floor (Subfloor coating)", "m2", 6400, 42.00, {"nrm": "3.6"}),
                ("3.7", "Internal partitions, NOC, MEP & BOH rooms (Internal walls)", "m2", 5200, 115.00, {"nrm": "3.7"}),
                ("3.8", "Acoustic & fire-rated doorsets, data-hall airlocks (Doorsets)", "pcs", 165, 3200.00, {"nrm": "3.8"}),
                ("3.9", "Suspended ceilings & finishes, admin/NOC (Admin ceilings)", "m2", 2600, 95.00, {"nrm": "3.9"}),
                ("3.10", "Floor finishes, vinyl/carpet & coatings, BOH (BOH floors)", "m2", 3400, 78.00, {"nrm": "3.10"}),
                ("3.11", "Painting, sealing & wall finishes (Painting)", "m2", 22000, 24.00, {"nrm": "3.11"}),
                ("3.12", "Joinery, NOC consoles & kitchenette fit-out (Joinery)", "lsum", 1, 420000.00, {"nrm": "3.12"}),
            ],
        ),
        # ── Electrical: HV / transformers / switchgear / UPS / gensets ───
        (
            "5.3",
            "5.3 - Services: Electrical (HV, UPS, generators & distribution)",
            {"nrm": "5.3"},
            [
                ("5.3.1", "HV intake, zone substation & ring main units 22 kV (HV intake)", "lsum", 1, 6800000.00, {"nrm": "5.3"}),
                ("5.3.2", "Package substations, 11 kV/415 V 2.5 MVA transformers (Transformers)", "pcs", 12, 385000.00, {"nrm": "5.3"}),
                ("5.3.3", "LV main switchboards, form 4 type 7 (Main switchboards)", "pcs", 16, 285000.00, {"nrm": "5.3"}),
                ("5.3.4", "Static UPS modules 1.25 MW with VRLA battery (UPS systems)", "pcs", 28, 420000.00, {"nrm": "5.3"}),
                ("5.3.5", "Standby diesel generators 2.5 MVA, acoustic enclosure (Generators)", "pcs", 14, 1450000.00, {"nrm": "5.3"}),
                ("5.3.6", "Bulk diesel fuel storage, day tanks & polishing (Fuel system)", "lsum", 1, 2850000.00, {"nrm": "5.3"}),
                ("5.3.7", "Busway distribution to data halls, 800-2500 A (Busway)", "m", 3200, 1250.00, {"nrm": "5.3"}),
                ("5.3.8", "Remote power panels & PDU distribution (RPP/PDU)", "pcs", 220, 28000.00, {"nrm": "5.3"}),
                ("5.3.9", "Sub-mains, power reticulation & cable ladder (Reticulation)", "m", 18000, 145.00, {"nrm": "5.3"}),
                ("5.3.10", "Automatic transfer & paralleling switchgear (ATS/sync)", "lsum", 1, 3200000.00, {"nrm": "5.3"}),
                ("5.3.11", "LED lighting, white space & BOH, controls (Lighting)", "m2", 18400, 58.00, {"nrm": "5.3"}),
                ("5.3.12", "Emergency & exit lighting AS 2293 (Emergency lighting)", "pcs", 620, 245.00, {"nrm": "5.3"}),
                ("5.3.13", "Earthing, bonding & lightning protection AS 1768 (Earthing)", "lsum", 1, 850000.00, {"nrm": "5.3"}),
                ("5.3.14", "Surge protection & power quality (Surge protection)", "lsum", 1, 385000.00, {"nrm": "5.3"}),
            ],
        ),
        # ── Mechanical: cooling, CRAC, chillers, ventilation ─────────────
        (
            "5.2",
            "5.2 - Services: Mechanical (Cooling, CRAC, chillers & ventilation)",
            {"nrm": "5.2"},
            [
                ("5.2.1", "Air-cooled chillers 1.6 MW, N+1, free-cooling (Chillers)", "pcs", 10, 1250000.00, {"nrm": "5.2"}),
                ("5.2.2", "Chilled-water pumps, dual-path, VSD (CHW pumps)", "pcs", 16, 145000.00, {"nrm": "5.2"}),
                ("5.2.3", "Chilled-water reticulation, welded steel DN300-500 (CHW pipework)", "m", 4800, 685.00, {"nrm": "5.2"}),
                ("5.2.4", "Thermal energy storage tanks, ride-through (TES tanks)", "pcs", 4, 480000.00, {"nrm": "5.2"}),
                ("5.2.5", "CRAC / CRAH units, in-row chilled-water, data halls (CRAC units)", "pcs", 110, 95000.00, {"nrm": "5.2"}),
                ("5.2.6", "Make-up air handling units with filtration (MUA AHUs)", "pcs", 12, 165000.00, {"nrm": "5.2"}),
                ("5.2.7", "Ductwork, dampers & attenuators (Ductwork)", "kg", 185000, 14.50, {"nrm": "5.2"}),
                ("5.2.8", "Admin & NOC comfort cooling, VRF (Comfort cooling)", "m2", 2600, 285.00, {"nrm": "5.2"}),
                ("5.2.9", "Generator & switchroom ventilation (Plant ventilation)", "lsum", 1, 1450000.00, {"nrm": "5.2"}),
                ("5.2.10", "Pipework insulation, lagging & cladding (Pipe insulation)", "m", 5200, 78.00, {"nrm": "5.2"}),
                ("5.2.11", "Mechanical thermal commissioning & IST (Mech Cx)", "lsum", 1, 1850000.00, {"nrm": "5.2"}),
            ],
        ),
        # ── Hydraulic services ───────────────────────────────────────────
        (
            "5.1",
            "5.1 - Services: Hydraulic (Plumbing & drainage)",
            {"nrm": "5.1"},
            [
                ("5.1.1", "Cold & hot water reticulation, copper/PEX (Water reticulation)", "m", 2600, 62.00, {"nrm": "5.1"}),
                ("5.1.2", "Sanitary drainage uPVC DN100/150 (Sanitary drainage)", "m", 1800, 78.00, {"nrm": "5.1"}),
                ("5.1.3", "Trade waste & fuel bund drainage with interceptor (Trade waste)", "lsum", 1, 285000.00, {"nrm": "5.1"}),
                ("5.1.4", "Stormwater drainage & on-site detention (Stormwater)", "lsum", 1, 485000.00, {"nrm": "5.1"}),
                ("5.1.5", "Sanitary fixtures & tapware, amenities (Fixtures)", "pcs", 64, 1850.00, {"nrm": "5.1"}),
                ("5.1.6", "Make-up & chiller plant water treatment (Water treatment)", "lsum", 1, 365000.00, {"nrm": "5.1"}),
                ("5.1.7", "Rainwater harvesting & reuse tanks (Rainwater reuse)", "lsum", 1, 165000.00, {"nrm": "5.1"}),
            ],
        ),
        # ── Fire suppression & detection (gas / VESDA) ───────────────────
        (
            "5.4",
            "5.4 - Services: Fire (Gaseous suppression, VESDA & sprinklers)",
            {"nrm": "5.4"},
            [
                ("5.4.1", "Inert-gas (IG-541) suppression to data halls ISO 14520 (Gas suppression)", "m2", 6400, 285.00, {"nrm": "5.4"}),
                ("5.4.2", "VESDA aspirating smoke detection, very-early warning (VESDA)", "m2", 6400, 58.00, {"nrm": "5.4"}),
                ("5.4.3", "Sprinkler system to BOH & plant AS 2118 (Sprinklers)", "m2", 12000, 42.00, {"nrm": "5.4"}),
                ("5.4.4", "Fire detection, addressable EWIS AS 1670 (Fire detection)", "m2", 18400, 24.00, {"nrm": "5.4"}),
                ("5.4.5", "Fire hydrants, hose reels & booster AS 2419 (Hydrants)", "lsum", 1, 485000.00, {"nrm": "5.4"}),
                ("5.4.6", "Fire pump set & on-site water storage tanks (Fire pumps)", "pcs", 2, 245000.00, {"nrm": "5.4"}),
                ("5.4.7", "Inert-gas cylinder banks & pipework (Gas cylinders)", "pcs", 48, 38000.00, {"nrm": "5.4"}),
            ],
        ),
        # ── Security, access control & DCIM ──────────────────────────────
        (
            "5.6",
            "5.6 - Services: Security, Communications & DCIM",
            {"nrm": "5.6"},
            [
                ("5.6.1", "Perimeter intrusion detection & PIDS fence (Perimeter security)", "m", 920, 485.00, {"nrm": "5.6"}),
                ("5.6.2", "Access control, anti-tailgate portals & mantrap (Access control)", "pcs", 86, 14500.00, {"nrm": "5.6"}),
                ("5.6.3", "IP CCTV surveillance & VMS, internal/external (CCTV)", "pcs", 240, 4200.00, {"nrm": "5.6"}),
                ("5.6.4", "Structured cabling cat.6A & backbone fibre (Structured cabling)", "m", 42000, 5.20, {"nrm": "5.6"}),
                ("5.6.5", "Meet-me rooms & carrier entry rooms fit-out (Meet-me rooms)", "pcs", 4, 285000.00, {"nrm": "5.6"}),
                ("5.6.6", "Building & data-centre management system DCIM/BMS (DCIM)", "lsum", 1, 2450000.00, {"nrm": "5.6"}),
                ("5.6.7", "Security control room & gatehouse fit-out (Control room)", "lsum", 1, 385000.00, {"nrm": "5.6"}),
            ],
        ),
        # ── External & site works ────────────────────────────────────────
        (
            "6",
            "6 - External & Site Works (Roads, hardstand & landscape)",
            {"nrm": "6"},
            [
                ("6.1", "Heavy-duty pavement, roads & loading hardstand (Pavements)", "m2", 14000, 165.00, {"nrm": "6.1"}),
                ("6.2", "Car parking, line marking & shade (Car parking)", "m2", 4200, 95.00, {"nrm": "6.2"}),
                ("6.3", "Generator yard & fuel-farm bunded paving (Generator yard)", "m2", 3600, 285.00, {"nrm": "6.3"}),
                ("6.4", "Authority connections, HV, water & telecoms (Authority connections)", "lsum", 1, 2850000.00, {"nrm": "6.4"}),
                ("6.5", "Site stormwater, swales & bio-retention (Site stormwater)", "lsum", 1, 685000.00, {"nrm": "6.5"}),
                ("6.6", "Soft landscape, planting & irrigation (Softscape)", "m2", 8500, 42.00, {"nrm": "6.6"}),
                ("6.7", "Boom gates, bollards & vehicle barriers (Vehicle barriers)", "lsum", 1, 285000.00, {"nrm": "6.7"}),
                ("6.8", "Site lighting & external signage (Site lighting)", "lsum", 1, 365000.00, {"nrm": "6.8"}),
            ],
        ),
    ],
    markups=[
        ("Builder's Preliminaries", 9.0, "overhead", "direct_cost"),
        ("Design & Construction Contingency", 6.0, "contingency", "direct_cost"),
        ("Builder's Margin (Overheads & Profit)", 5.5, "profit", "cumulative"),
        ("GST (Goods & Services Tax)", 10.0, "tax", "cumulative"),
    ],
    total_months=24,
    tender_name="Base Build & Shell Trade Package",
    tender_companies=[
        ("Kandarra Building", "tenders@kandarra.example", 0.99),
        ("Brenlake Constructions", "estimating@brenlake-au.example", 1.04),
        ("Formara Pty Ltd", "tenders@formara.example", 1.02),
    ],
    tender_packages=[
        (
            "Base Build & Shell Trade Package",
            "Bulk earthworks, substructure, tilt-up/precast shell, structural steel roof",
            "evaluating",
            [
                ("Kandarra Building", "tenders@kandarra.example", 0.99),
                ("Brenlake Constructions", "estimating@brenlake-au.example", 1.04),
                ("Formara Pty Ltd", "tenders@formara.example", 1.02),
            ],
        ),
        (
            "Critical Power Package (Electrical)",
            "HV intake, transformers, switchgear, UPS, generators, busway & fuel",
            "evaluating",
            [
                ("Wexlon Group", "estimating@wexlon.example", 0.98),
                ("Talloway Group", "tenders@talloway.example", 1.05),
                ("Kelverne Australia", "tenders@kelverne.example", 1.02),
            ],
        ),
        (
            "Critical Cooling Package (Mechanical)",
            "Chillers, CHW reticulation, CRAC/CRAH, ventilation & thermal commissioning",
            "evaluating",
            [
                ("R.T. Halligan Group", "tenders@halligan.example", 0.99),
                ("Wexlon Air", "estimating@wexlon.example", 1.06),
                ("Corrindale Air Conditioning", "tenders@corrindale.example", 1.03),
            ],
        ),
        (
            "Fire & Security Package",
            "Inert-gas suppression, VESDA, sprinklers, access control, CCTV & DCIM",
            "evaluating",
            [
                ("Marrowvale Construction & Fitout", "tenders@marrowvale.example", 0.97),
                ("Sentigard Fire & Security", "estimating@sentigard.example", 1.04),
                ("Aurenex Building Solutions", "tenders@aurenex.example", 1.03),
            ],
        ),
        (
            "White Space Fit-out Package",
            "Raised floor, hot-aisle containment, cable management & data-hall finishes",
            "evaluating",
            [
                ("Formara Pty Ltd", "tenders@formara.example", 0.98),
                ("Marrowvale Construction & Fitout", "tenders@marrowvale.example", 1.05),
                ("Draskell Constructions", "estimating@draskell.example", 1.02),
            ],
        ),
    ],
    project_metadata={
        "address": "120 Doherty's Road, Truganina (West Melbourne), VIC 3029",
        # Kept deliberately. The bird this name opens with is a denied token in
        # tests/unit/test_demo_seed_has_no_real_firm_names.py, and this name
        # passes only because that rule hashes maximal runs and so reads
        # "kestrelink" as one token - narrow the rule and this goes red on its
        # own. It stays because a fresh coinage is likelier to hit a live firm
        # than a reviewed name is. Still owed: the token itself is unsearched.
        "client": "Kestrelink Infrastructure Partners Pty Ltd",
        "architect": "Verrowmead Studio",
        "quantity_surveyor": "Cranleigh Partnership (AIQS)",
        "structural_engineer": "Calderyn Engineers",
        "mep_engineer": "Trenholme Group (mission-critical)",
        "gba_m2": 18400,
        "site_area_ha": 4.2,
        "critical_it_load_mw": 30,
        "data_halls": 4,
        "tier": "Uptime Institute Tier III - Concurrently Maintainable",
        "redundancy": "N+1 (power & cooling)",
        "pue_target": 1.3,
        "structure_system": "Tilt-up / precast concrete shell + long-span structural-steel roof",
        "construction_standards": [
            "NCC 2022 (Building Code of Australia)",
            "AS 3600 Concrete structures",
            "AS 4100 Steel structures",
            "AS 1170 Structural design actions",
            "AS 1668 The use of ventilation and air-conditioning in buildings",
            "AS 2118 Automatic fire sprinkler systems",
            "AS 1670 Fire detection, warning & control",
            "ISO 14520 Gaseous fire-extinguishing systems",
            "ANSI/TIA-942 Data centre infrastructure reference",
        ],
        "regulator": "City of Melton / Victorian Building Authority (VBA)",
        "permit_notes": (
            "Building permit under the Building Act 1993 (Vic); planning permit "
            "under the Melton Planning Scheme; Section J (NCC 2022) energy "
            "compliance and EPA Victoria works approval for fuel storage lodged."
        ),
        "sustainability": "PUE design target 1.3; air-cooled free-cooling chillers; rainwater reuse; NABERS for Data Centres rating pathway",
        "procurement": "Design & Construct (lump sum)",
    },
    budget_boq_name="Elemental Cost Plan - AIQS / NRM Elemental",
    planned_budget=348000000.00,
    actual_spend_ratio=0.42,
    spi_override=0.97,
    cpi_override=1.02,
)
