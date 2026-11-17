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
    validation_rule_sets=["boq_quality", "survey_core", "surfaces_volumes"],
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
