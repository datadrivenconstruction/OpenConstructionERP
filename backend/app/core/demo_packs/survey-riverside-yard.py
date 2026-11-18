# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Survey course demo: Riverside Yard, a 100 x 60 m platform in EPSG 32633
# ---------------------------------------------------------------------------
# The install also seeds the survey data (CRS, control, existing ground, a
# closed traverse, two surfaces and a draft volume V-001) through
# app.modules.surfaces_volumes.demo. Lesson numbers live in
# app/modules/survey_core/demo/riverside/expected.json.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="survey-riverside-yard",
    project_name="Riverside Yard (survey demo)",
    project_description=(
        "Training project for the survey course: a 100 x 60 m storage yard platform levelled "
        "at 34.30 m on a gently sloping riverside plot. Control points, an existing ground "
        "survey of 77 points, a closed traverse and the design pad are loaded; the volume "
        "between existing ground and the pad is computed as a draft for the learner to confirm "
        "and send to the earthworks line of the bill."
    ),
    region="DE",
    classification_standard="din276",
    currency="EUR",
    locale="en",
    address={
        "street": "Riverside Yard",
        "city": "Berlin",
        "postcode": "10557",
        "country": "Germany",
        "lat": 52.5101,
        "lng": 13.3651,
    },
    validation_rule_sets=["boq_quality", "survey_core", "surfaces_volumes", "stockpiles", "mine_survey"],
    boq_name="Earthworks - Riverside Yard",
    boq_description="Earthworks bill for the yard platform; the excavation quantity comes from survey volume V-001.",
    boq_metadata={"phase": "Survey course", "price_level": "Demo rates (EUR, excl VAT)"},
    sections=[
        (
            "1",
            "1 - Earthworks",
            {"din276": "310"},
            [
                ("1.01", "Topsoil strip and stockpile", "m2", 6000, 2.80, {"din276": "311"}),
                ("1.02", "Bulk excavation", "m3", 1500, 9.50, {"din276": "312"}),
                ("1.03", "Fill to platform, compacted in layers", "m3", 300, 14.00, {"din276": "313"}),
                ("1.04", "Disposal of surplus off site", "m3", 1200, 21.00, {"din276": "314"}),
            ],
        ),
        (
            "2",
            "2 - Site preparation",
            {"din276": "320"},
            [
                ("2.01", "Site clearance and vegetation removal", "m2", 7200, 1.40, {"din276": "320"}),
                ("2.02", "Tree felling and stump removal", "pcs", 14, 185.00, {"din276": "320"}),
                ("2.03", "Temporary site fencing, 2.0 m", "m", 340, 12.50, {"din276": "320"}),
                ("2.04", "Site access road, temporary gravel", "m2", 480, 16.00, {"din276": "320"}),
                ("2.05", "Wheel wash and site entrance", "lsum", 1, 3200.00, {"din276": "320"}),
                ("2.06", "Setting out and as-staked survey", "lsum", 1, 2800.00, {"din276": "320"}),
                ("2.07", "Existing utility location trial pits", "pcs", 12, 210.00, {"din276": "320"}),
                ("2.08", "Dewatering sump pump hire", "lsum", 1, 4100.00, {"din276": "320"}),
                ("2.09", "Silt fence along the river edge", "m", 180, 9.80, {"din276": "320"}),
                ("2.10", "Temporary site office and welfare", "lsum", 1, 6500.00, {"din276": "320"}),
            ],
        ),
        (
            "3",
            "3 - Platform formation",
            {"din276": "330"},
            [
                ("3.01", "Cut to formation level, machine", "m3", 1500, 4.20, {"din276": "330"}),
                ("3.02", "Trim and compact formation", "m2", 6000, 1.90, {"din276": "330"}),
                ("3.03", "Geotextile separation layer", "m2", 6200, 2.60, {"din276": "330"}),
                ("3.04", "Sub-base type 1, 300 mm", "m3", 1800, 32.00, {"din276": "330"}),
                ("3.05", "Capping layer, 200 mm", "m3", 1200, 24.50, {"din276": "330"}),
                ("3.06", "Proof rolling and plate load tests", "pcs", 18, 95.00, {"din276": "330"}),
                ("3.07", "Crushed stone blinding layer", "m3", 300, 36.00, {"din276": "330"}),
                ("3.08", "Edge compaction and slope trimming", "m", 320, 6.40, {"din276": "330"}),
                ("3.09", "Settlement monitoring points", "pcs", 12, 140.00, {"din276": "330"}),
                ("3.10", "Imported select fill", "m3", 650, 18.50, {"din276": "330"}),
            ],
        ),
        (
            "4",
            "4 - Drainage",
            {"din276": "340"},
            [
                ("4.01", "Trench excavation for drains", "m3", 420, 11.00, {"din276": "340"}),
                ("4.02", "PVC drain pipe DN 300", "m", 260, 48.00, {"din276": "340"}),
                ("4.03", "PVC drain pipe DN 150", "m", 190, 29.00, {"din276": "340"}),
                ("4.04", "Concrete manhole DN 1000", "pcs", 8, 1350.00, {"din276": "340"}),
                ("4.05", "Gully with trap", "pcs", 16, 320.00, {"din276": "340"}),
                ("4.06", "Pipe bedding and surround, gravel", "m3", 210, 34.00, {"din276": "340"}),
                ("4.07", "Backfill to drain trenches", "m3", 380, 9.00, {"din276": "340"}),
                ("4.08", "Oil separator, 20 l/s", "pcs", 1, 7800.00, {"din276": "340"}),
                ("4.09", "Outfall headwall to river", "pcs", 1, 4200.00, {"din276": "340"}),
                ("4.10", "CCTV survey of drains", "m", 450, 3.80, {"din276": "340"}),
            ],
        ),
        (
            "5",
            "5 - Surfacing and edges",
            {"din276": "350"},
            [
                ("5.01", "Asphalt base course, 80 mm", "m2", 4800, 17.50, {"din276": "350"}),
                ("5.02", "Asphalt wearing course, 40 mm", "m2", 4800, 11.80, {"din276": "350"}),
                ("5.03", "Bitumen tack coat", "m2", 4800, 0.90, {"din276": "350"}),
                ("5.04", "Concrete kerb, 100 x 250", "m", 420, 24.00, {"din276": "350"}),
                ("5.05", "Concrete hardstanding slab, 200 mm", "m2", 900, 58.00, {"din276": "350"}),
                ("5.06", "Reinforcement mesh A252", "kg", 9800, 1.35, {"din276": "350"}),
                ("5.07", "Expansion joints, sealed", "m", 260, 7.50, {"din276": "350"}),
                ("5.08", "Line marking and bay numbering", "lsum", 1, 1900.00, {"din276": "350"}),
                ("5.09", "Bollards, steel", "pcs", 24, 115.00, {"din276": "350"}),
                ("5.10", "Wheel stops", "pcs", 30, 42.00, {"din276": "350"}),
            ],
        ),
        (
            "6",
            "6 - Services and finishes",
            {"din276": "360"},
            [
                ("6.01", "Duct bank, 4 x 110 mm", "m", 310, 38.00, {"din276": "360"}),
                ("6.02", "Draw pit, precast", "pcs", 9, 420.00, {"din276": "360"}),
                ("6.03", "Floodlight mast, 8 m", "pcs", 6, 2150.00, {"din276": "360"}),
                ("6.04", "Mast foundation, concrete", "pcs", 6, 640.00, {"din276": "360"}),
                ("6.05", "Site lighting cabling", "m", 420, 14.50, {"din276": "360"}),
                ("6.06", "Security fence, 2.4 m palisade", "m", 330, 68.00, {"din276": "360"}),
                ("6.07", "Double leaf gate, 6 m", "pcs", 1, 3900.00, {"din276": "360"}),
                ("6.08", "Topsoil and seeding to verges", "m2", 1300, 3.60, {"din276": "360"}),
                ("6.09", "Hedge planting", "m", 160, 11.50, {"din276": "360"}),
                ("6.10", "As-built survey and handover records", "lsum", 1, 2400.00, {"din276": "360"}),
                ("6.11", "Cleaning and final inspection", "lsum", 1, 1100.00, {"din276": "360"}),
            ],
        ),
    ],
    markups=[("Site overheads", 8.0, "overhead", "direct_cost")],
    total_months=14,
    tender_name="Earthworks - Riverside Yard",
    tender_companies=[
        ("Uferbau Erdbau GmbH", "tender@uferbau.example", 1.0),
        ("Spreeland Tiefbau GmbH", "angebot@spreeland-tiefbau.example", 1.04),
    ],
    project_metadata={"course": "survey", "dataset": "riverside_yard", "epsg": 32633, "platform_level_m": 34.3},
)
