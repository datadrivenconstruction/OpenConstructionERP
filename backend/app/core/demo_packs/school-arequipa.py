# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: peru-pe - Public school, Arequipa
# ---------------------------------------------------------------------------
# A public works budget (presupuesto de obra) under the procurement law: direct
# cost by partida, gastos generales, utilidad, then the IGV at 18 percent. The
# contract is paid by monthly valuations (valorizaciones) that hold a ten
# percent retention as the performance guarantee.
#
# INDICATIVE, PLAINLY: rates are market build-ups for Arequipa in 2026 soles,
# without IGV, not taken from any published price list; quantities are derived
# by ratio from the stated areas; the gastos generales and utilidad figures are
# this bid's own; the parties are invented. The advance payments of a public
# contract (adelanto directo and de materiales) are flagged for expert review
# in the pack and are not modelled here.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="school-arequipa",
    project_name="Institución Educativa Primaria Los Andes - Arequipa (Public School, Arequipa)",
    project_description=(
        "Construcción de una institución educativa pública de primaria en Arequipa: 18 aulas en dos "
        "pabellones de dos pisos, biblioteca, laboratorio, sala de usos múltiples, servicios higiénicos, "
        "losa deportiva y cerco perimetral. Estructura de concreto armado y albañilería confinada según "
        "la Norma Técnica E.030 y E.070. Área construida de unos 3.200 m2 sobre un terreno de 8.500 m2. "
        "Obra pública por contrato con valorizaciones mensuales."
    ),
    region="PE",
    classification_standard="masterformat",
    currency="PEN",
    locale="es",
    address={
        "street": "Calle Los Andes s/n, Cerro Colorado",
        "city": "Arequipa",
        "postcode": "04014",
        "country": "Peru",
        "lat": -16.3720,
        "lng": -71.5760,
    },
    validation_rule_sets=["peru", "boq_quality", "project_completeness"],
    boq_name="Presupuesto de Obra - I.E. Primaria Los Andes",
    boq_description=(
        "Presupuesto por partidas a costo directo, con gastos generales, utilidad e IGV al 18 por ciento "
        "como líneas propias. Precios de Arequipa 2026 en soles, sin IGV."
    ),
    boq_metadata={
        "standard": "Presupuesto de obra por partidas",
        "phase": "Expediente técnico - presupuesto base",
        "base_date": "2026-Q1",
        "price_level": "Arequipa 2026 (PEN, sin IGV)",
    },
    sections=[
        (
            "01",
            "01 - Obras Provisionales y Preliminares (Temporary works and preliminaries)",
            {"masterformat": "01"},
            [
                ("01.01", "Cartel de obra (Site sign)", "pcs", 1, 3800.00, {"masterformat": "01 58 00"}),
                (
                    "01.02",
                    "Cerco provisional y almacén (Hoarding and stores)",
                    "lsum",
                    1,
                    64000.00,
                    {"masterformat": "01 52 00"},
                ),
                (
                    "01.03",
                    "Trazo, nivelación y replanteo (Setting out)",
                    "m2",
                    8500,
                    3.80,
                    {"masterformat": "01 71 23"},
                ),
                ("01.04", "Seguridad y salud en obra (Site safety)", "lsum", 1, 96000.00, {"masterformat": "01 35 29"}),
                (
                    "01.05",
                    "Movilización y desmovilización (Mobilisation)",
                    "lsum",
                    1,
                    48000.00,
                    {"masterformat": "01 54 00"},
                ),
            ],
        ),
        (
            "02",
            "02 - Movimiento de Tierras (Earthworks)",
            {"masterformat": "31"},
            [
                (
                    "02.01",
                    "Excavación de zanjas y zapatas (Trench and footing excavation)",
                    "m3",
                    2100,
                    34.00,
                    {"masterformat": "31 23 16"},
                ),
                (
                    "02.02",
                    "Relleno compactado con material propio (Compacted backfill)",
                    "m3",
                    1400,
                    29.00,
                    {"masterformat": "31 23 23"},
                ),
                (
                    "02.03",
                    "Eliminación de material excedente (Spoil removal)",
                    "m3",
                    900,
                    36.00,
                    {"masterformat": "31 23 23"},
                ),
                (
                    "02.04",
                    "Nivelación y compactación de plataforma (Platform grading)",
                    "m2",
                    4200,
                    8.50,
                    {"masterformat": "31 22 00"},
                ),
            ],
        ),
        (
            "03",
            "03 - Estructuras de Concreto Armado (Reinforced concrete structure)",
            {"masterformat": "03"},
            [
                (
                    "03.01",
                    "Concreto f'c=210 kg/cm2 en cimentación (Foundations)",
                    "m3",
                    560,
                    520.00,
                    {"masterformat": "03 31 00"},
                ),
                (
                    "03.02",
                    "Concreto f'c=210 kg/cm2 en columnas y placas (Columns and walls)",
                    "m3",
                    330,
                    690.00,
                    {"masterformat": "03 31 00"},
                ),
                (
                    "03.03",
                    "Concreto f'c=210 kg/cm2 en vigas y losas aligeradas (Beams and ribbed slabs)",
                    "m3",
                    780,
                    640.00,
                    {"masterformat": "03 31 00"},
                ),
                (
                    "03.04",
                    "Acero corrugado fy=4200 kg/cm2 (Reinforcing steel)",
                    "kg",
                    210000,
                    5.20,
                    {"masterformat": "03 21 00"},
                ),
                ("03.05", "Encofrado y desencofrado (Formwork)", "m2", 8400, 55.00, {"masterformat": "03 11 00"}),
                (
                    "03.06",
                    "Ladrillo de arcilla para losa aligerada (Hollow clay blocks)",
                    "pcs",
                    38000,
                    3.60,
                    {"masterformat": "04 22 00"},
                ),
            ],
        ),
        (
            "04",
            "04 - Albañilería y Acabados (Masonry and finishes)",
            {"masterformat": "09"},
            [
                (
                    "04.01",
                    "Muros de albañilería confinada (Confined masonry walls)",
                    "m2",
                    7200,
                    92.00,
                    {"masterformat": "04 22 00"},
                ),
                (
                    "04.02",
                    "Tarrajeo de muros y cielorrasos (Plastering)",
                    "m2",
                    14500,
                    31.00,
                    {"masterformat": "09 24 00"},
                ),
                (
                    "04.03",
                    "Piso de cemento pulido y cerámico (Floor finishes)",
                    "m2",
                    3200,
                    78.00,
                    {"masterformat": "09 30 00"},
                ),
                (
                    "04.04",
                    "Carpintería metálica, puertas y ventanas (Metal doors and windows)",
                    "m2",
                    1100,
                    340.00,
                    {"masterformat": "08 11 00"},
                ),
                ("04.05", "Pintura látex en muros (Latex paint)", "m2", 16800, 17.50, {"masterformat": "09 91 00"}),
                (
                    "04.06",
                    "Pizarras y mobiliario fijo (Fixed boards and furniture)",
                    "lsum",
                    1,
                    85000.00,
                    {"masterformat": "12 30 00"},
                ),
            ],
        ),
        (
            "05",
            "05 - Cobertura (Roofing)",
            {"masterformat": "07"},
            [
                (
                    "05.01",
                    "Cobertura de losa con impermeabilizante (Waterproofed slab roof)",
                    "m2",
                    1900,
                    68.00,
                    {"masterformat": "07 13 00"},
                ),
                (
                    "05.02",
                    "Cobertura ligera de pabellón de usos múltiples (Light roof, multipurpose hall)",
                    "m2",
                    650,
                    195.00,
                    {"masterformat": "07 41 00"},
                ),
            ],
        ),
        (
            "06",
            "06 - Instalaciones Sanitarias y Eléctricas (Plumbing and electrical)",
            {"masterformat": "22"},
            [
                (
                    "06.01",
                    "Redes de agua y desagüe (Water and drainage)",
                    "lsum",
                    1,
                    210000.00,
                    {"masterformat": "22 11 00"},
                ),
                ("06.02", "Aparatos sanitarios (Sanitary fixtures)", "pcs", 96, 680.00, {"masterformat": "22 40 00"}),
                (
                    "06.03",
                    "Cisterna y tanque elevado (Cistern and tank)",
                    "lsum",
                    1,
                    118000.00,
                    {"masterformat": "22 11 23"},
                ),
                (
                    "06.04",
                    "Instalaciones eléctricas interiores (Interior electrical)",
                    "m2",
                    3200,
                    98.00,
                    {"masterformat": "26 05 00"},
                ),
                (
                    "06.05",
                    "Tableros y puesta a tierra (Boards and earthing)",
                    "lsum",
                    1,
                    72000.00,
                    {"masterformat": "26 24 00"},
                ),
                ("06.06", "Luminarias LED (LED luminaires)", "pcs", 640, 120.00, {"masterformat": "26 51 00"}),
            ],
        ),
        (
            "07",
            "07 - Obras Exteriores (External works)",
            {"masterformat": "32"},
            [
                (
                    "07.01",
                    "Losa deportiva multiuso (Multi-sport court)",
                    "m2",
                    800,
                    165.00,
                    {"masterformat": "32 18 00"},
                ),
                (
                    "07.02",
                    "Veredas y patio de formación (Paths and assembly yard)",
                    "m2",
                    2200,
                    72.00,
                    {"masterformat": "32 13 13"},
                ),
                (
                    "07.03",
                    "Cerco perimétrico de albañilería y reja (Perimeter fence)",
                    "m",
                    380,
                    640.00,
                    {"masterformat": "32 31 00"},
                ),
                (
                    "07.04",
                    "Áreas verdes y limpieza final (Landscaping and final cleaning)",
                    "lsum",
                    1,
                    58000.00,
                    {"masterformat": "32 90 00"},
                ),
            ],
        ),
    ],
    markups=[
        ("Gastos generales", 10.0, "overhead", "direct_cost"),
        ("Utilidad", 7.0, "profit", "direct_cost"),
        ("IGV (18 %)", 18.0, "tax", "cumulative"),
    ],
    total_months=10,
    tender_name="Contrato de Obra - Institución Educativa",
    tender_companies=[
        ("Consorcio Misti Obras", "procesos@misti-obras.example", 0.97),
        ("Constructora Chachani", "procesos@chachani-constructora.example", 1.03),
        ("Edificaciones Volcán Sur", "procesos@volcan-sur.example", 1.00),
    ],
    progress_claims=(0.12, 0.30, 0.52),
    claim_retention=0.10,
    project_metadata={
        "address": "Calle Los Andes s/n, Cerro Colorado, 04014 Arequipa, Perú",
        "client": "Unidad Ejecutora de Inversiones Educativas (ficticia)",
        "gfa_m2": 3200,
        "site_area_m2": 8500,
        "classrooms": 18,
        "storeys": 2,
        "construction_standards": [
            "Reglamento Nacional de Edificaciones (RNE)",
            "Norma Técnica E.030 Diseño Sismorresistente",
            "Norma Técnica E.070 Albañilería",
        ],
        "estimating_method": "Presupuesto por partidas con gastos generales, utilidad e IGV",
        "contract": "Obra pública por contrato con valorizaciones mensuales",
        "igv_note": ("Todos los precios son sin IGV. El IGV del 18 por ciento se aplica como línea aparte."),
        "valuation_note": (
            "Cada valorización mensual retiene el 10 por ciento como garantía de fiel cumplimiento. "
            "Los adelantos directo y de materiales están señalados para revisión de un experto."
        ),
    },
)
