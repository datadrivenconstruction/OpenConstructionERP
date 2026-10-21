# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Showcase: full-service group - mixed-use hub, Riyadh (KSA)
# ---------------------------------------------------------------------------
# One project that runs all six business lines of a full-service group: A
# consultancy (design and supervision), B building construction, C site
# development, D landscaping, E architectural and interior fit-out, F FF&E
# procurement (furniture, fixtures and equipment schedule with suppliers).
# Section letters mark the business line, so the bill totals roll up per line.
# Rates are Riyadh 2026 market rates in SAR, exclusive of VAT (15% is a
# separate markup). Arabic project name is kept in project_metadata["name_ar"].
# ---------------------------------------------------------------------------


def _c(mf: str, sbc: str = "SBC 201") -> dict:
    return {"masterformat": mf, "sbc": sbc}


TEMPLATE = DemoTemplate(
    demo_id="full-showcase-riyadh",
    project_name="Al Malqa Business and Residence Hub, Riyadh",
    project_description=(
        "Mixed-use hub in Al Malqa, north Riyadh: a 7-storey office building and a 6-storey serviced "
        "residence on a shared podium, with a landscaped plaza and parking courtyard. One project "
        "runs six business lines: design and supervision consultancy, building construction, site "
        "development, landscaping, architectural and interior fit-out, and FF&E procurement with a "
        "supplier-priced furniture, fixtures and equipment schedule. GFA about 14,200 m2, direct "
        "cost about SAR 78 million."
    ),
    region="SA",
    classification_standard="masterformat",
    currency="SAR",
    locale="en",
    address={
        "street": "Al Malqa District, King Abdulaziz Road",
        "city": "Riyadh",
        "postcode": "13521",
        "country": "Saudi Arabia",
        "lat": 24.8130,
        "lng": 46.6020,
    },
    project_code="KSA-FULL-RUH-2026",
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Group BOQ by business line - Al Malqa Business and Residence Hub",
    boq_description=(
        "Sections A to F are the six business lines: consultancy, building construction, site "
        "development, landscaping, fit-out and FF&E, with Saudi Building Code references."
    ),
    boq_metadata={
        "standard": "MasterFormat divisions + SBC 2024 (SBC 201/301/304/401/501/601/701/801)",
        "phase": "Contract budget by business line",
        "base_date": "2026-Q2",
        "price_level": "Riyadh 2026 (SAR, excl. VAT)",
        "business_lines": "A consultancy; B building; C site development; D landscaping; E fit-out; F FF&E",
    },
    sections=[
        (
            "A",
            "A - Consultancy: design and supervision",
            _c("01 11 00"),
            [
                (
                    "A.01",
                    "Concept and schematic design, architecture and engineering",
                    "h",
                    3200,
                    330.00,
                    _c("01 11 00"),
                ),
                ("A.02", "Detailed design, all disciplines", "h", 9800, 290.00, _c("01 12 00")),
                ("A.03", "BIM coordination and clash detection", "h", 3600, 200.00, _c("01 12 00")),
                ("A.04", "Authority approvals - Amanah and Civil Defense", "lsum", 1, 140000.00, _c("01 41 00")),
                ("A.05", "Tender documents, BOQ and bid evaluation", "h", 2400, 310.00, _c("00 01 00")),
                ("A.06", "Site supervision team", "month", 20, 118000.00, _c("01 40 00")),
                ("A.07", "Interior design and FF&E specification", "h", 2100, 300.00, _c("01 12 00")),
                ("A.08", "Project management and cost control", "month", 20, 46000.00, _c("01 31 00")),
            ],
        ),
        (
            "B",
            "B - Building construction: structure and envelope",
            _c("03 00 00", "SBC 304"),
            [
                ("B.01", "Bulk excavation and shoring, one basement", "m3", 24500, 44.00, _c("31 23 16", "SBC 301")),
                ("B.02", "Bored piles 800 mm", "m", 2900, 520.00, _c("31 63 29", "SBC 301")),
                ("B.03", "Raft and pile caps C40", "m3", 3300, 545.00, _c("03 31 00", "SBC 304")),
                ("B.04", "Columns, cores and walls C45", "m3", 2900, 640.00, _c("03 30 00", "SBC 304")),
                ("B.05", "Slabs and beams C40", "m3", 6100, 585.00, _c("03 30 00", "SBC 304")),
                ("B.06", "Reinforcement B500B", "t", 3050, 4150.00, _c("03 21 00", "SBC 304")),
                ("B.07", "Formwork, all elements", "m2", 48000, 82.00, _c("03 11 00", "SBC 304")),
                ("B.08", "External and internal blockwork", "m2", 22000, 88.00, _c("04 22 00")),
                ("B.09", "Roof and basement waterproofing, insulation", "m2", 9800, 96.00, _c("07 13 00", "SBC 601")),
                (
                    "B.10",
                    "Curtain wall and aluminium glazing, solar control",
                    "m2",
                    5400,
                    1250.00,
                    _c("08 44 13", "SBC 601"),
                ),
                ("B.11", "Stone and metal cladding to podium", "m2", 2300, 640.00, _c("04 43 00")),
                (
                    "B.12",
                    "Building MEP: HVAC, electrical, plumbing, fire",
                    "m2",
                    14200,
                    1480.00,
                    _c("23 00 00", "SBC 501"),
                ),
                ("B.13", "Passenger and service lifts", "pcs", 7, 495000.00, _c("14 21 00", "SBC 801")),
                ("B.14", "Preliminaries, cranes and site staff, 20 months", "month", 20, 168000.00, _c("01 00 00")),
            ],
        ),
        (
            "C",
            "C - Site development: infrastructure and external works",
            _c("31 00 00"),
            [
                ("C.01", "Site clearance and grading", "m2", 21000, 12.00, _c("31 10 00")),
                ("C.02", "Engineered fill and compaction", "m3", 12400, 38.00, _c("31 23 23", "SBC 301")),
                ("C.03", "Storm water drainage, pipes and manholes", "m", 1650, 410.00, _c("33 40 00")),
                ("C.04", "Water, fire-water and sewer connections", "lsum", 1, 1250000.00, _c("33 10 00", "SBC 701")),
                (
                    "C.05",
                    "MV connection and external electrical network",
                    "lsum",
                    1,
                    1680000.00,
                    _c("26 11 00", "SBC 401"),
                ),
                ("C.06", "Asphalt roads and parking, 100 mm", "m2", 7800, 128.00, _c("32 12 16")),
                ("C.07", "Kerbs, retaining walls and perimeter wall", "m", 1450, 780.00, _c("32 16 00")),
                ("C.08", "Underground water tanks and pump rooms", "lsum", 1, 960000.00, _c("33 16 00")),
            ],
        ),
        (
            "D",
            "D - Landscaping: hardscape and softscape",
            _c("32 90 00"),
            [
                ("D.01", "Plaza paving, natural stone", "m2", 3200, 395.00, _c("32 14 40")),
                ("D.02", "Interlock paving, paths and courtyard", "m2", 4800, 118.00, _c("32 14 13")),
                ("D.03", "Date palms and shade trees", "pcs", 310, 2650.00, _c("32 93 00")),
                ("D.04", "Shrubs, groundcover and turf", "m2", 6400, 54.00, _c("32 93 00")),
                ("D.05", "Drip and sprinkler irrigation with controller", "m2", 6400, 28.00, _c("32 84 00")),
                ("D.06", "Water feature and plaza lighting", "lsum", 1, 880000.00, _c("32 84 00")),
                ("D.07", "Pergolas and shade structures", "pcs", 9, 165000.00, _c("13 33 00")),
                ("D.08", "Establishment maintenance, 12 months", "month", 12, 48000.00, _c("32 01 90")),
            ],
        ),
        (
            "E",
            "E - Architectural and interior fit-out",
            _c("09 00 00"),
            [
                ("E.01", "Office floors: raised floor and carpet tile", "m2", 6800, 260.00, _c("09 69 00")),
                ("E.02", "Office partitions, glazed and drywall", "m2", 7400, 340.00, _c("09 21 00")),
                ("E.03", "Suspended ceilings, acoustic and gypsum", "m2", 11200, 118.00, _c("09 51 00")),
                ("E.04", "Marble and tile to lobbies and wet areas", "m2", 5600, 310.00, _c("09 30 00")),
                ("E.05", "Wall finishes, paint and wallcovering", "m2", 36000, 38.00, _c("09 91 00")),
                ("E.06", "Internal doors, timber and glass", "pcs", 540, 3100.00, _c("08 14 00")),
                ("E.07", "Residence apartments: kitchens and joinery", "pcs", 62, 58000.00, _c("12 35 00")),
                ("E.08", "Residence apartments: bathrooms complete", "pcs", 62, 36000.00, _c("22 40 00", "SBC 701")),
                ("E.09", "Reception and lobby feature joinery", "lsum", 1, 1250000.00, _c("12 35 00")),
                ("E.10", "Acoustic treatment to conference and meeting rooms", "m2", 1900, 420.00, _c("09 84 00")),
                ("E.11", "Signage and wayfinding, interior", "lsum", 1, 340000.00, _c("10 14 00")),
                ("E.12", "Feature lighting and decorative fittings", "lsum", 1, 1180000.00, _c("26 51 00", "SBC 401")),
            ],
        ),
        (
            "F",
            "F - FF&E procurement: furniture, fixtures and equipment schedule",
            _c("12 00 00"),
            [
                ("F.01", "Executive desks and credenzas", "pcs", 38, 9800.00, _c("12 52 00")),
                ("F.02", "Open-plan workstations with screens", "pcs", 320, 4600.00, _c("12 52 00")),
                ("F.03", "Ergonomic task chairs", "pcs", 380, 1850.00, _c("12 52 00")),
                ("F.04", "Meeting tables, 8 to 20 seats", "pcs", 24, 14500.00, _c("12 52 00")),
                ("F.05", "Conference chairs", "pcs", 260, 1650.00, _c("12 52 00")),
                ("F.06", "Reception counters and lounge seating", "lsum", 1, 640000.00, _c("12 52 00")),
                ("F.07", "Filing and storage units", "pcs", 220, 1900.00, _c("12 52 00")),
                ("F.08", "Serviced residence living room sets", "pcs", 62, 18500.00, _c("12 50 00")),
                ("F.09", "Serviced residence bedroom sets, king", "pcs", 62, 21500.00, _c("12 50 00")),
                ("F.10", "Dining sets and kitchen stools", "pcs", 62, 7800.00, _c("12 50 00")),
                ("F.11", "Curtains, blinds and soft furnishings", "pcs", 62, 14200.00, _c("12 20 00")),
                ("F.12", "Kitchen appliance packages, residence", "pcs", 62, 16500.00, _c("11 31 00")),
                ("F.13", "Washers and dryers, residence", "pcs", 62, 5200.00, _c("11 31 00")),
                ("F.14", "Televisions and AV, residence and meeting rooms", "pcs", 140, 4300.00, _c("27 41 00")),
                ("F.15", "Meeting room video-conference systems", "pcs", 24, 38000.00, _c("27 41 00")),
                ("F.16", "Pantry equipment and vending", "lsum", 1, 380000.00, _c("11 40 00")),
                ("F.17", "Gym equipment, residence amenity floor", "lsum", 1, 560000.00, _c("11 68 00")),
                ("F.18", "Artwork and decorative accessories", "lsum", 1, 420000.00, _c("12 10 00")),
                ("F.19", "Lobby and outdoor furniture", "lsum", 1, 480000.00, _c("12 93 00")),
                ("F.20", "FF&E delivery, installation and handover", "lsum", 1, 310000.00, _c("01 77 00")),
            ],
        ),
    ],
    markups=[
        ("Site overheads and preliminaries", 7.0, "overhead", "direct_cost"),
        ("Head-office overheads", 4.0, "overhead", "direct_cost"),
        ("Profit", 7.0, "profit", "direct_cost"),
        ("Contingency", 3.0, "contingency", "direct_cost"),
        ("VAT (15%)", 15.0, "tax", "cumulative"),
    ],
    total_months=20,
    tender_name="Building structure and envelope package",
    tender_companies=[
        ("Dirah Structural Contracting Co.", "bids@dirahstruct.example", 0.99),
        ("Sahab Infrastructure and Landscape", "tenders@sahabinfra.example", 1.02),
        ("Mizan Interiors and Fit-out", "estimation@mizaninteriors.example", 1.03),
        ("Riwaq Furniture Trading", "sales@riwaqfurniture.example", 1.01),
        ("Faisal Office Systems", "sales@faisaloffice.example", 1.04),
        ("Najd Hospitality Equipment", "bids@najdhospitality.example", 1.02),
    ],
    tender_packages=[
        (
            "Building structure and envelope subcontract",
            "Piling, concrete frame, blockwork, waterproofing, curtain wall and cladding.",
            "awarded",
            [
                ("Dirah Structural Contracting Co.", "bids@dirahstruct.example", 0.99),
                ("Sahab Infrastructure and Landscape", "tenders@sahabinfra.example", 1.06),
            ],
        ),
        (
            "Site development and landscaping subcontract",
            "External networks, roads, plaza paving, planting and irrigation.",
            "awarded",
            [
                ("Sahab Infrastructure and Landscape", "tenders@sahabinfra.example", 1.02),
                ("Dirah Structural Contracting Co.", "bids@dirahstruct.example", 1.08),
            ],
        ),
        (
            "Interior fit-out subcontract",
            "Office floors, partitions, ceilings, finishes, doors, joinery and bathrooms.",
            "evaluating",
            [
                ("Mizan Interiors and Fit-out", "estimation@mizaninteriors.example", 1.03),
                ("Dirah Structural Contracting Co.", "bids@dirahstruct.example", 1.07),
            ],
        ),
        (
            "FF&E fit-out supply: office furniture",
            "Executive desks, workstations, task chairs, meeting tables, storage and reception counters.",
            "evaluating",
            [
                ("Faisal Office Systems", "sales@faisaloffice.example", 1.04),
                ("Riwaq Furniture Trading", "sales@riwaqfurniture.example", 1.01),
            ],
        ),
        (
            "FF&E fit-out supply: serviced residence furniture",
            "Living room sets, bedroom sets, dining sets, curtains, kitchen appliances and washers.",
            "issued",
            [
                ("Riwaq Furniture Trading", "sales@riwaqfurniture.example", 1.01),
                ("Najd Hospitality Equipment", "bids@najdhospitality.example", 1.02),
            ],
        ),
        (
            "FF&E fit-out supply: amenity and pantry equipment",
            "Pantry equipment, vending, gym equipment, lobby and outdoor furniture, artwork.",
            "draft",
            [
                ("Najd Hospitality Equipment", "bids@najdhospitality.example", 1.02),
            ],
        ),
    ],
    schedule_activities=[
        ("Design and authority approvals", "2026-04-01", "2026-06-30"),
        ("Mobilisation, piling and excavation", "2026-06-01", "2026-08-31"),
        ("Raft and basement structure", "2026-08-15", "2026-11-15"),
        ("Podium and tower frame", "2026-11-01", "2027-04-30"),
        ("Site development and external networks", "2026-12-01", "2027-05-31"),
        ("Envelope, curtain wall and waterproofing", "2027-03-01", "2027-08-31"),
        ("MEP installation", "2027-04-01", "2027-10-31"),
        ("Interior fit-out", "2027-07-01", "2027-11-30"),
        ("Landscaping and plaza", "2027-09-01", "2027-12-15"),
        ("FF&E delivery and installation", "2027-10-15", "2027-12-31"),
        ("Testing, commissioning and handover", "2027-11-15", "2028-01-31"),
    ],
    planned_budget=77500000.0,
    actual_spend_ratio=0.19,
    spi_override=0.98,
    cpi_override=1.02,
    project_metadata={
        "name_ar": "مجمع الملقا للأعمال والسكن - الرياض",
        "address": "Al Malqa District, Riyadh 13521, Saudi Arabia",
        "client": "Malqa Business Properties Co.",
        "architect": "Zahra Architectural Consultants",
        "structural_engineer": "Mizan Structural Engineering Office",
        "mep_engineer": "Hayyan MEP Engineering Office",
        "quantity_surveyor": "Qimah Cost Consultants",
        "main_contractor": "Dirah Structural Contracting Co.",
        "business_line": "Full-service group: consultancy, building, site development, landscaping, fit-out, FF&E",
        "contract_form": "Design-and-build with provisional FF&E schedule; monthly interim certificates, 5% retention",
        "gfa_m2": 14200,
        "storeys": 7,
        "units": "Offices and 62 serviced residences",
        "building_code": "Saudi Building Code SBC 2024",
        "code_parts": "SBC 201, 301, 304, 401, 501, 601, 701, 801",
        "vat_note": "All rates exclusive of VAT. KSA VAT of 15% is applied as a separate markup line.",
        "regulator": "Riyadh Municipality (Amanah) building permit; Saudi Civil Defense approval",
    },
)
