# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Showcase: site development and landscaping - community park, Dammam (KSA)
# ---------------------------------------------------------------------------
# A 14-hectare community park in the Eastern Province: earthworks, storm water
# and irrigation networks, lighting, roads and parking, hardscape paving,
# concrete structures, play and sports areas, softscape planting and site
# furniture. The bill is by work package so quantities (m2, m3, m, pcs) drive
# the subcontracts and the progress claims. Rates are Dammam 2026 market rates
# in SAR, exclusive of VAT (15% is a separate markup). Arabic project name is
# kept in project_metadata["name_ar"].
# ---------------------------------------------------------------------------


def _c(mf: str, sbc: str = "SBC 201") -> dict:
    return {"masterformat": mf, "sbc": sbc}


TEMPLATE = DemoTemplate(
    demo_id="site-development-dammam",
    project_name="Al Fanateer Community Park, Dammam",
    project_description=(
        "Site development and landscaping of a 14-hectare community park in Dammam: bulk earthworks, "
        "storm water and treated-effluent irrigation networks, power and lighting, internal roads and "
        "parking, paved promenades and plazas, concrete retaining walls and pavilions, play and sports "
        "areas, soft landscape with native and drought-tolerant planting, and site furniture. "
        "Direct cost about SAR 38 million."
    ),
    region="SA",
    classification_standard="masterformat",
    currency="SAR",
    locale="en",
    address={
        "street": "Al Fanateer District, King Saud Road",
        "city": "Dammam",
        "postcode": "32241",
        "country": "Saudi Arabia",
        "lat": 26.4207,
        "lng": 50.0888,
    },
    project_code="KSA-SITE-DMM-2026",
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Site development BOQ - Al Fanateer Community Park",
    boq_description="Priced bill of quantities by work package: earthworks, utilities, hardscape and softscape.",
    boq_metadata={
        "standard": "MasterFormat divisions 02, 03, 26, 31, 32, 33 + SBC 2024",
        "phase": "Tender BOQ",
        "base_date": "2026-Q2",
        "price_level": "Dammam 2026 (SAR, excl. VAT)",
    },
    sections=[
        (
            "01",
            "01 - Preliminaries and enabling works",
            _c("01 00 00"),
            [
                ("01.01", "Site establishment, offices and welfare, 12 months", "month", 12, 48000.00, _c("01 52 00")),
                ("01.02", "Project management and site supervision team", "month", 12, 96000.00, _c("01 31 00")),
                ("01.03", "Topographic survey and setting out", "ha", 14, 6200.00, _c("01 71 23")),
                ("01.04", "Temporary fencing and traffic management", "m", 2400, 85.00, _c("01 56 00")),
                ("01.05", "Dust control and water for compaction", "month", 9, 22000.00, _c("01 57 00")),
                ("01.06", "Insurance, bonds and permits", "lsum", 1, 310000.00, _c("01 41 00")),
                ("01.07", "Material testing and quality control", "lsum", 1, 160000.00, _c("01 45 00")),
            ],
        ),
        (
            "02",
            "02 - Earthworks and ground preparation",
            _c("31 00 00", "SBC 301"),
            [
                ("02.01", "Site clearance and removal of debris", "m2", 140000, 3.80, _c("31 10 00")),
                ("02.02", "Bulk cut to formation levels", "m3", 118000, 11.50, _c("31 23 16", "SBC 301")),
                ("02.03", "Imported select fill, compacted in layers", "m3", 82000, 36.00, _c("31 23 23", "SBC 301")),
                ("02.04", "Topsoil import and spreading 300 mm", "m3", 24000, 58.00, _c("32 91 13")),
                ("02.05", "Feature mounds and berms, shaped", "m3", 16500, 42.00, _c("31 22 00")),
                ("02.06", "Ground improvement and proof rolling", "m2", 68000, 6.50, _c("31 32 00", "SBC 301")),
                ("02.07", "Excavation for trenches and structures", "m3", 31500, 24.00, _c("31 23 16")),
                ("02.08", "Backfill to trenches and structures", "m3", 27800, 31.00, _c("31 23 23")),
                ("02.09", "Surplus soil removal to licensed tip", "m3", 20500, 27.00, _c("31 23 23")),
            ],
        ),
        (
            "03",
            "03 - Storm water and drainage",
            _c("33 40 00"),
            [
                ("03.01", "HDPE storm drain pipes 300-600 mm", "m", 4200, 245.00, _c("33 41 00")),
                ("03.02", "Precast concrete culvert and headwalls", "m", 640, 1180.00, _c("33 41 16")),
                ("03.03", "Manholes and catch basins", "pcs", 148, 6400.00, _c("33 49 00")),
                ("03.04", "Detention basin lining and outlet structure", "m2", 5200, 128.00, _c("33 46 00")),
                ("03.05", "Subsoil drainage to sports fields", "m", 3600, 92.00, _c("33 46 00")),
                ("03.06", "Connection to public storm water system", "lsum", 1, 380000.00, _c("33 40 00")),
            ],
        ),
        (
            "04",
            "04 - Irrigation and water supply",
            _c("32 80 00"),
            [
                ("04.01", "TSE irrigation main, HDPE 250-110 mm", "m", 5400, 165.00, _c("33 11 00")),
                ("04.02", "Pump station, filtration and controller", "lsum", 1, 1250000.00, _c("32 84 00")),
                ("04.03", "Underground storage tanks 2 x 800 m3", "pcs", 2, 640000.00, _c("33 16 00")),
                ("04.04", "Pop-up sprinklers to turf areas", "m2", 62000, 14.00, _c("32 84 23")),
                ("04.05", "Drip irrigation to trees and shrubs", "m2", 41000, 12.50, _c("32 84 00")),
                ("04.06", "Potable water network and drinking fountains", "lsum", 1, 540000.00, _c("33 10 00")),
                ("04.07", "Central irrigation control and flow sensors", "lsum", 1, 310000.00, _c("32 84 00")),
            ],
        ),
        (
            "05",
            "05 - Power and lighting",
            _c("26 00 00", "SBC 401"),
            [
                (
                    "05.01",
                    "Medium voltage connection and 2 no. transformers",
                    "lsum",
                    1,
                    1380000.00,
                    _c("26 12 00", "SBC 401"),
                ),
                ("05.02", "LV distribution boards and cabling", "m", 9800, 118.00, _c("26 05 00", "SBC 401")),
                ("05.03", "Pole-mounted LED lighting, 8 m", "pcs", 120, 7400.00, _c("26 56 00", "SBC 401")),
                ("05.04", "Pathway bollard lights", "pcs", 460, 2100.00, _c("26 56 00", "SBC 401")),
                ("05.05", "Sports field floodlighting", "pcs", 24, 18500.00, _c("26 56 00", "SBC 401")),
                ("05.06", "Landscape uplighting and feature lighting", "pcs", 280, 1250.00, _c("26 56 00", "SBC 401")),
                ("05.07", "CCTV and public address, pole mounted", "lsum", 1, 720000.00, _c("28 23 00", "SBC 401")),
                ("05.08", "Solar canopies over car parking, 150 kWp", "kWp", 150, 3400.00, _c("26 31 00", "SBC 601")),
            ],
        ),
        (
            "06",
            "06 - Roads and parking",
            _c("32 10 00"),
            [
                ("06.01", "Road base course, crushed aggregate 250 mm", "m2", 22500, 48.00, _c("32 11 00")),
                ("06.02", "Asphalt wearing course 100 mm in two layers", "m2", 22500, 92.00, _c("32 12 16")),
                ("06.03", "Concrete kerbs and edge restraints", "m", 8600, 68.00, _c("32 16 00")),
                ("06.04", "Parking bay markings and signage", "lsum", 1, 185000.00, _c("32 17 00")),
                ("06.05", "Bus drop-off bay with concrete paving", "m2", 1600, 210.00, _c("32 13 13")),
                ("06.06", "Perimeter fence and vehicle gates", "m", 1900, 560.00, _c("32 31 00")),
            ],
        ),
        (
            "07",
            "07 - Hardscape: paving and plazas",
            _c("32 14 00"),
            [
                ("07.01", "Interlocking concrete paving, promenades", "m2", 18500, 118.00, _c("32 14 13")),
                ("07.02", "Natural stone paving to main plaza", "m2", 4800, 395.00, _c("32 14 40")),
                ("07.03", "Granite steps and ramps", "m2", 1250, 640.00, _c("32 14 40")),
                ("07.04", "Concrete jogging track with rubberised surface", "m2", 9400, 168.00, _c("32 18 00")),
                ("07.05", "Decorative stamped concrete to amphitheatre", "m2", 2100, 210.00, _c("32 13 16")),
                ("07.06", "Tactile paving and accessibility ramps", "m", 1800, 145.00, _c("32 14 00")),
                ("07.07", "Granular sub-base for paved areas", "m2", 36000, 32.00, _c("32 11 00")),
            ],
        ),
        (
            "08",
            "08 - Concrete structures and pavilions",
            _c("03 00 00", "SBC 304"),
            [
                ("08.01", "Reinforced concrete retaining walls C35", "m3", 2150, 760.00, _c("03 30 00", "SBC 304")),
                ("08.02", "Pavilion foundations and slabs C35", "m3", 820, 690.00, _c("03 30 00", "SBC 304")),
                ("08.03", "Reinforcement B500B", "t", 340, 4150.00, _c("03 21 00", "SBC 304")),
                ("08.04", "Formwork to walls and slabs", "m2", 9800, 82.00, _c("03 11 00", "SBC 304")),
                ("08.05", "Shade pavilions, steel with fabric canopy", "pcs", 14, 285000.00, _c("13 33 00")),
                ("08.06", "Service building, toilets and prayer room", "lsum", 1, 3250000.00, _c("13 34 00")),
                ("08.07", "Amphitheatre seating, precast steps", "m", 1450, 540.00, _c("03 41 00")),
            ],
        ),
        (
            "09",
            "09 - Play and sports facilities",
            _c("32 33 00"),
            [
                (
                    "09.01",
                    "Children's play areas, equipment and rubber safety surface",
                    "lsum",
                    1,
                    1850000.00,
                    _c("32 18 16"),
                ),
                ("09.02", "Multi-sport courts, football and basketball", "pcs", 4, 480000.00, _c("32 18 23")),
                ("09.03", "Artificial turf football pitch", "m2", 5400, 245.00, _c("32 18 23")),
                ("09.04", "Outdoor fitness stations", "pcs", 18, 28500.00, _c("11 68 00")),
                ("09.05", "Skate and bike park, concrete", "m2", 1900, 520.00, _c("32 33 00")),
            ],
        ),
        (
            "10",
            "10 - Softscape and planting",
            _c("32 90 00"),
            [
                ("10.01", "Date palms, 4-6 m clear trunk", "pcs", 380, 3200.00, _c("32 93 00")),
                ("10.02", "Shade trees, native and adapted species", "pcs", 1250, 780.00, _c("32 93 00")),
                ("10.03", "Shrubs and groundcover, drought tolerant", "m2", 21500, 46.00, _c("32 93 00")),
                ("10.04", "Seasonal flower beds", "m2", 3200, 85.00, _c("32 93 43")),
                ("10.05", "Turf sod, Bermuda grass", "m2", 62000, 21.00, _c("32 92 23")),
                ("10.06", "Tree pit preparation and staking", "pcs", 1630, 140.00, _c("32 93 00")),
                ("10.07", "Mulching and soil conditioning", "m2", 24700, 9.50, _c("32 91 00")),
                ("10.08", "Establishment maintenance, 12 months", "month", 12, 135000.00, _c("32 01 90")),
            ],
        ),
        (
            "11",
            "11 - Site furniture and signage",
            _c("12 93 00"),
            [
                ("11.01", "Park benches, precast and timber composite", "pcs", 320, 1850.00, _c("12 93 00")),
                ("11.02", "Litter bins and recycling stations", "pcs", 210, 920.00, _c("12 93 00")),
                ("11.03", "Picnic tables with shade", "pcs", 80, 6400.00, _c("12 93 00")),
                ("11.04", "Wayfinding and information signage", "lsum", 1, 420000.00, _c("10 14 00")),
                ("11.05", "Bicycle racks and bollards", "pcs", 140, 780.00, _c("12 93 00")),
                ("11.06", "Public art and water feature, plaza", "lsum", 1, 1350000.00, _c("32 84 00")),
            ],
        ),
    ],
    markups=[
        ("Site overheads", 7.0, "overhead", "direct_cost"),
        ("Head-office overheads", 4.0, "overhead", "direct_cost"),
        ("Profit", 7.0, "profit", "direct_cost"),
        ("Contingency", 4.0, "contingency", "direct_cost"),
        ("VAT (15%)", 15.0, "tax", "cumulative"),
    ],
    total_months=12,
    tender_name="Earthworks and drainage subcontract",
    tender_companies=[
        ("Thumama Earthworks and Roads Co.", "bids@thumamaearth.example", 0.97),
        ("Hijaz Irrigation and Water Systems", "tenders@hijazirrigation.example", 1.02),
        ("Wahat Landscape Contracting", "estimation@wahatlandscape.example", 1.00),
        ("Sharqiya Paving and Hardscape", "bids@sharqiyapaving.example", 1.04),
        ("Nakheel Gulf Nurseries", "sales@nakheelgulf.example", 1.01),
    ],
    tender_packages=[
        (
            "Earthworks and enabling subcontract",
            "Site clearance, bulk cut and fill, soil import and ground improvement.",
            "awarded",
            [
                ("Thumama Earthworks and Roads Co.", "bids@thumamaearth.example", 0.97),
                ("Sharqiya Paving and Hardscape", "bids@sharqiyapaving.example", 1.05),
            ],
        ),
        (
            "Roads and drainage subcontract",
            "Storm water drainage, road base, asphalt, kerbs and parking.",
            "awarded",
            [
                ("Thumama Earthworks and Roads Co.", "bids@thumamaearth.example", 0.98),
                ("Sharqiya Paving and Hardscape", "bids@sharqiyapaving.example", 1.06),
            ],
        ),
        (
            "Irrigation and water utilities subcontract",
            "TSE irrigation main, pump station, tanks, sprinklers and drip irrigation controls.",
            "awarded",
            [
                ("Hijaz Irrigation and Water Systems", "tenders@hijazirrigation.example", 1.02),
                ("Wahat Landscape Contracting", "estimation@wahatlandscape.example", 1.08),
            ],
        ),
        (
            "Hardscape paving and plazas subcontract",
            "Interlock and stone paving, jogging track, plazas and steps.",
            "evaluating",
            [
                ("Sharqiya Paving and Hardscape", "bids@sharqiyapaving.example", 1.04),
                ("Thumama Earthworks and Roads Co.", "bids@thumamaearth.example", 1.07),
            ],
        ),
        (
            "Landscaping and softscape planting subcontract",
            "Date palms, shade trees, shrubs, turf and 12 months establishment maintenance.",
            "issued",
            [
                ("Wahat Landscape Contracting", "estimation@wahatlandscape.example", 1.0),
                ("Nakheel Gulf Nurseries", "sales@nakheelgulf.example", 1.01),
            ],
        ),
    ],
    schedule_activities=[
        ("Mobilisation, survey and setting out", "2026-04-01", "2026-04-25"),
        ("Clearing and bulk earthworks", "2026-04-20", "2026-07-31"),
        ("Storm water and utility networks", "2026-06-01", "2026-09-15"),
        ("Irrigation main, tanks and pump station", "2026-08-01", "2026-11-15"),
        ("Roads, parking and kerbs", "2026-09-15", "2026-12-20"),
        ("Hardscape paving and plazas", "2026-11-01", "2027-02-28"),
        ("Structures, pavilions and service building", "2026-10-15", "2027-02-15"),
        ("Play and sports facilities", "2027-01-15", "2027-03-31"),
        ("Softscape planting and turf", "2027-02-01", "2027-04-30"),
        ("Lighting, furniture and commissioning", "2027-03-15", "2027-04-30"),
    ],
    planned_budget=37800000.0,
    actual_spend_ratio=0.34,
    spi_override=0.96,
    cpi_override=1.01,
    project_metadata={
        "name_ar": "حديقة الفنيتير المجتمعية - الدمام",
        "address": "Al Fanateer District, Dammam 32241, Saudi Arabia",
        "client": "Eastern Province Municipality - Parks Department",
        "architect": "Rimal Landscape Architecture Studio",
        "structural_engineer": "Mizan Structural Engineering Office",
        "mep_engineer": "Hayyan MEP Engineering Office",
        "quantity_surveyor": "Qimah Cost Consultants",
        "main_contractor": "Thumama Earthworks and Roads Co.",
        "business_line": "Site development and landscaping",
        "contract_form": "Unit-rate contract (remeasured) with monthly interim payments, 5% retention",
        "area_ha": 14,
        "building_code": "Saudi Building Code SBC 2024",
        "code_parts": "SBC 201, 301, 304, 401, 601",
        "irrigation_note": "Treated sewage effluent (TSE) irrigation, native and drought-tolerant planting",
        "vat_note": "All rates exclusive of VAT. KSA VAT of 15% is applied as a separate markup line.",
        "regulator": "Eastern Province Municipality; Saudi Civil Defense for pavilions and service building",
    },
)
