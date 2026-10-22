# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: peru-pe - Private hospital, Lima San Isidro
# ---------------------------------------------------------------------------
# A Peruvian budget (presupuesto de obra) lists the direct cost by partida,
# then adds the gastos generales and the utilidad as lines of their own, then
# the IGV at 18 percent. The contractor bills the owner a monthly valuation
# (valorizacion); on this private contract each one holds a ten percent
# retention against the performance guarantee, and a construction invoice above
# S/ 700 carries the 4 percent detraction.
#
# WHAT IS INDICATIVE HERE, PLAINLY.
#
# 1. The rates are market build-ups for Lima in 2026 soles, without IGV. They
#    are not taken from any published price list. The partida numbers are this
#    bill's own item numbers.
# 2. Quantities are derived by ratio from the stated areas, not measured off
#    drawings.
# 3. The gastos generales and utilidad percentages are this bid's own figures;
#    they differ from bid to bid and ship no statutory value.
# 4. The advance payments (adelanto directo and adelanto de materiales) that a
#    public contract allows are not modelled on this private contract.
# 5. All parties, RUC numbers and the detraction account are invented.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="hospital-lima",
    project_name="Clínica Privada Mirador Andino - Lima, San Isidro (Private Hospital, Lima)",
    project_description=(
        "Construcción de una clínica privada de 120 camas en San Isidro, Lima. Un sótano de "
        "estacionamiento y servicios, seis pisos con emergencia, 6 quirófanos, unidad de cuidados "
        "intensivos, hospitalización, consulta externa, laboratorio y diagnóstico por imágenes. "
        "Estructura de concreto armado con placas, diseñada según la Norma Técnica E.030 de diseño "
        "sismorresistente. Área construida de unos 6.500 m2 sobre un terreno de 2.600 m2. "
        "Presupuesto por partidas con gastos generales, utilidad e IGV; valorizaciones mensuales."
    ),
    region="PE",
    classification_standard="masterformat",
    currency="PEN",
    locale="es",
    address={
        "street": "Av. Camino Real 1450, San Isidro",
        "city": "Lima",
        "postcode": "15036",
        "country": "Peru",
        "lat": -12.0975,
        "lng": -77.0360,
    },
    validation_rule_sets=["peru", "boq_quality", "project_completeness"],
    boq_name="Presupuesto de Obra - Clínica Mirador Andino",
    boq_description=(
        "Presupuesto por partidas a costo directo, con gastos generales, utilidad e IGV al 18 por ciento "
        "como líneas propias. Precios de Lima 2026 en soles, sin IGV."
    ),
    boq_metadata={
        "standard": "Presupuesto de obra por partidas",
        "phase": "Expediente técnico - presupuesto base",
        "base_date": "2026-Q1",
        "price_level": "Lima 2026 (PEN, sin IGV)",
    },
    sections=[
        (
            "01",
            "01 - Obras Provisionales y Trabajos Preliminares (Temporary works and preliminaries)",
            {"masterformat": "01"},
            [
                (
                    "01.01",
                    "Cartel de obra y cerco provisional (Site sign and hoarding)",
                    "lsum",
                    1,
                    85000.00,
                    {"masterformat": "01 58 00"},
                ),
                (
                    "01.02",
                    "Campamento, oficinas y almacén de obra (Site offices and stores)",
                    "m2",
                    400,
                    650.00,
                    {"masterformat": "01 52 00"},
                ),
                (
                    "01.03",
                    "Trazo, nivelación y replanteo (Setting out)",
                    "m2",
                    2600,
                    6.50,
                    {"masterformat": "01 71 23"},
                ),
                (
                    "01.04",
                    "Plan de seguridad y salud en obra (Site safety plan)",
                    "lsum",
                    1,
                    420000.00,
                    {"masterformat": "01 35 29"},
                ),
                (
                    "01.05",
                    "Movilización y desmovilización de equipos (Mobilisation)",
                    "lsum",
                    1,
                    180000.00,
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
                    "Excavación masiva del sótano (Bulk excavation)",
                    "m3",
                    9800,
                    28.00,
                    {"masterformat": "31 23 16"},
                ),
                (
                    "02.02",
                    "Eliminación de material excedente (Spoil removal)",
                    "m3",
                    12300,
                    32.00,
                    {"masterformat": "31 23 23"},
                ),
                (
                    "02.03",
                    "Perfilado y compactación del fondo (Subgrade compaction)",
                    "m2",
                    2600,
                    9.50,
                    {"masterformat": "31 23 23"},
                ),
                (
                    "02.04",
                    "Relleno con material de préstamo compactado (Imported backfill)",
                    "m3",
                    1900,
                    58.00,
                    {"masterformat": "31 23 23"},
                ),
                (
                    "02.05",
                    "Entibado y calzaduras perimetrales (Shoring and underpinning)",
                    "m2",
                    1150,
                    310.00,
                    {"masterformat": "31 50 00"},
                ),
                (
                    "02.06",
                    "Excavación de zanjas para redes e instalaciones (Utility trenches)",
                    "m3",
                    1250,
                    42.00,
                    {"masterformat": "31 23 16"},
                ),
                (
                    "02.07",
                    "Relleno y compactación de zanjas (Trench backfill)",
                    "m3",
                    1100,
                    45.00,
                    {"masterformat": "31 23 23"},
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
                    "Solado de concreto e=10 cm (Blinding concrete)",
                    "m2",
                    2600,
                    38.00,
                    {"masterformat": "03 30 00"},
                ),
                (
                    "03.02",
                    "Concreto f'c=280 kg/cm2 en platea y zapatas (Raft and footings)",
                    "m3",
                    2350,
                    640.00,
                    {"masterformat": "03 31 00"},
                ),
                (
                    "03.03",
                    "Concreto f'c=280 kg/cm2 en columnas y placas (Columns and shear walls)",
                    "m3",
                    1450,
                    780.00,
                    {"masterformat": "03 31 00"},
                ),
                (
                    "03.04",
                    "Concreto f'c=280 kg/cm2 en vigas y losas (Beams and slabs)",
                    "m3",
                    3100,
                    720.00,
                    {"masterformat": "03 31 00"},
                ),
                (
                    "03.05",
                    "Acero corrugado fy=4200 kg/cm2 (Reinforcing steel)",
                    "kg",
                    780000,
                    5.40,
                    {"masterformat": "03 21 00"},
                ),
                ("03.06", "Encofrado y desencofrado (Formwork)", "m2", 29500, 62.00, {"masterformat": "03 11 00"}),
                (
                    "03.07",
                    "Juntas sísmicas y waterstop (Seismic joints and waterstops)",
                    "m",
                    420,
                    145.00,
                    {"masterformat": "03 15 00"},
                ),
                (
                    "03.08",
                    "Concreto f'c=210 kg/cm2 en cisterna y muros de contención (Cistern and retaining walls)",
                    "m3",
                    620,
                    610.00,
                    {"masterformat": "03 31 00"},
                ),
                (
                    "03.09",
                    "Curado y protección del concreto (Concrete curing)",
                    "m2",
                    11500,
                    4.20,
                    {"masterformat": "03 39 00"},
                ),
            ],
        ),
        (
            "04",
            "04 - Arquitectura y Acabados (Architecture and finishes)",
            {"masterformat": "09"},
            [
                (
                    "04.01",
                    "Tabiquería seca con placa RH (Drywall partitions)",
                    "m2",
                    14500,
                    118.00,
                    {"masterformat": "09 21 16"},
                ),
                ("04.02", "Tarrajeo y enlucido de muros (Plastering)", "m2", 6200, 36.00, {"masterformat": "09 24 00"}),
                (
                    "04.03",
                    "Piso vinílico homogéneo y porcelanato (Clinical flooring)",
                    "m2",
                    5900,
                    210.00,
                    {"masterformat": "09 65 00"},
                ),
                (
                    "04.04",
                    "Cielo raso desmontable y de drywall (Ceilings)",
                    "m2",
                    5600,
                    98.00,
                    {"masterformat": "09 51 00"},
                ),
                (
                    "04.05",
                    "Ventanas y mamparas de aluminio con vidrio (Windows and glazed screens)",
                    "m2",
                    1350,
                    520.00,
                    {"masterformat": "08 51 13"},
                ),
                (
                    "04.06",
                    "Puertas cortafuego y hospitalarias (Fire and hospital doors)",
                    "pcs",
                    410,
                    1650.00,
                    {"masterformat": "08 14 00"},
                ),
                (
                    "04.07",
                    "Pintura lavable antibacteriana (Washable paint)",
                    "m2",
                    22000,
                    24.00,
                    {"masterformat": "09 91 00"},
                ),
                (
                    "04.08",
                    "Contrapiso e=5 cm (Screed)",
                    "m2",
                    5900,
                    42.00,
                    {"masterformat": "03 53 00"},
                ),
                (
                    "04.09",
                    "Zócalos y contrazócalos sanitarios (Coved skirtings)",
                    "m",
                    6200,
                    38.00,
                    {"masterformat": "09 65 00"},
                ),
                (
                    "04.10",
                    "Cerámico en servicios higiénicos y áreas húmedas (Wall tiling)",
                    "m2",
                    3100,
                    95.00,
                    {"masterformat": "09 30 00"},
                ),
                (
                    "04.11",
                    "Carpintería de madera y muebles fijos de enfermería (Joinery and fixed nursing furniture)",
                    "lsum",
                    1,
                    380000.00,
                    {"masterformat": "06 40 00"},
                ),
            ],
        ),
        (
            "05",
            "05 - Cobertura e Impermeabilización (Roofing and waterproofing)",
            {"masterformat": "07"},
            [
                (
                    "05.01",
                    "Impermeabilización de cobertura y sótano (Waterproofing)",
                    "m2",
                    3900,
                    78.00,
                    {"masterformat": "07 13 00"},
                ),
                (
                    "05.02",
                    "Cobertura liviana y parapetos (Light roof and parapets)",
                    "m2",
                    700,
                    210.00,
                    {"masterformat": "07 41 00"},
                ),
                (
                    "05.03",
                    "Juntas de dilatación y sellos de cobertura (Roof joints and sealants)",
                    "m",
                    380,
                    55.00,
                    {"masterformat": "07 92 00"},
                ),
            ],
        ),
        (
            "06",
            "06 - Instalaciones Sanitarias (Plumbing and fire water)",
            {"masterformat": "22"},
            [
                (
                    "06.01",
                    "Red de agua fría y caliente (Cold and hot water)",
                    "lsum",
                    1,
                    520000.00,
                    {"masterformat": "22 11 00"},
                ),
                (
                    "06.02",
                    "Red de desagüe y ventilación (Drainage and venting)",
                    "lsum",
                    1,
                    380000.00,
                    {"masterformat": "22 13 00"},
                ),
                (
                    "06.03",
                    "Aparatos sanitarios y grifería hospitalaria (Fixtures)",
                    "pcs",
                    285,
                    1150.00,
                    {"masterformat": "22 40 00"},
                ),
                (
                    "06.04",
                    "Cisterna y equipo de bombeo (Cistern and pumps)",
                    "lsum",
                    1,
                    760000.00,
                    {"masterformat": "22 11 23"},
                ),
                (
                    "06.05",
                    "Red de rociadores contra incendio (Sprinklers)",
                    "m2",
                    6500,
                    85.00,
                    {"masterformat": "21 13 00"},
                ),
                (
                    "06.06",
                    "Planta de ablandamiento de agua (Water softening plant)",
                    "lsum",
                    1,
                    210000.00,
                    {"masterformat": "22 31 00"},
                ),
                (
                    "06.07",
                    "Calentadores a gas y tanques de agua caliente (Hot water heaters and tanks)",
                    "pcs",
                    4,
                    38000.00,
                    {"masterformat": "22 33 00"},
                ),
            ],
        ),
        (
            "07",
            "07 - Instalaciones Eléctricas y Comunicaciones (Electrical and communications)",
            {"masterformat": "26"},
            [
                (
                    "07.01",
                    "Subestación y tablero general (Substation and switchgear)",
                    "lsum",
                    1,
                    1350000.00,
                    {"masterformat": "26 13 00"},
                ),
                (
                    "07.02",
                    "Grupo electrógeno de emergencia (Standby generator sets)",
                    "pcs",
                    2,
                    520000.00,
                    {"masterformat": "26 32 13"},
                ),
                (
                    "07.03",
                    "Circuitos, tuberías y cableado (Circuits and wiring)",
                    "m2",
                    6500,
                    195.00,
                    {"masterformat": "26 05 00"},
                ),
                ("07.04", "Luminarias LED (LED luminaires)", "pcs", 2300, 185.00, {"masterformat": "26 51 00"}),
                (
                    "07.05",
                    "Puesta a tierra y pararrayos (Earthing and lightning protection)",
                    "lsum",
                    1,
                    210000.00,
                    {"masterformat": "26 41 00"},
                ),
                (
                    "07.06",
                    "Energía ininterrumpida para quirófanos (UPS for operating theatres)",
                    "lsum",
                    1,
                    640000.00,
                    {"masterformat": "26 33 00"},
                ),
                (
                    "07.07",
                    "Cableado estructurado, voz, datos y CCTV (Data, voice and CCTV)",
                    "m2",
                    6500,
                    75.00,
                    {"masterformat": "27 10 00"},
                ),
                (
                    "07.08",
                    "Sistema de llamado de enfermeras (Nurse call system)",
                    "lsum",
                    1,
                    230000.00,
                    {"masterformat": "27 52 23"},
                ),
            ],
        ),
        (
            "08",
            "08 - Instalaciones Mecánicas y Médicas (Mechanical and medical systems)",
            {"masterformat": "23"},
            [
                (
                    "08.01",
                    "Climatización y presurización de quirófanos y UCI (Theatre and ICU HVAC)",
                    "m2",
                    2100,
                    1150.00,
                    {"masterformat": "23 30 00"},
                ),
                (
                    "08.02",
                    "Climatización de áreas generales (General air conditioning)",
                    "m2",
                    4400,
                    310.00,
                    {"masterformat": "23 81 00"},
                ),
                (
                    "08.03",
                    "Gases medicinales: oxígeno, aire y vacío (Medical gases)",
                    "pcs",
                    360,
                    2450.00,
                    {"masterformat": "22 63 00"},
                ),
                (
                    "08.04",
                    "Ascensores camilleros y de pasajeros (Bed and passenger lifts)",
                    "pcs",
                    6,
                    285000.00,
                    {"masterformat": "14 21 00"},
                ),
                (
                    "08.05",
                    "Detección y alarma de incendio (Fire detection and alarm)",
                    "lsum",
                    1,
                    480000.00,
                    {"masterformat": "28 31 00"},
                ),
                (
                    "08.06",
                    "Extracción y ventilación de baños y cocinas (Extraction and ventilation)",
                    "m2",
                    1800,
                    65.00,
                    {"masterformat": "23 34 00"},
                ),
            ],
        ),
        (
            "09",
            "09 - Obras Exteriores y Entrega (External works and handover)",
            {"masterformat": "32"},
            [
                (
                    "09.01",
                    "Pavimentos y veredas exteriores (External paving)",
                    "m2",
                    2400,
                    95.00,
                    {"masterformat": "32 13 13"},
                ),
                (
                    "09.02",
                    "Áreas verdes y cerco perimetral (Landscaping and fence)",
                    "lsum",
                    1,
                    240000.00,
                    {"masterformat": "32 90 00"},
                ),
                (
                    "09.03",
                    "Limpieza final y entrega de obra (Final cleaning and handover)",
                    "lsum",
                    1,
                    150000.00,
                    {"masterformat": "01 74 00"},
                ),
                (
                    "09.04",
                    "Accesos vehiculares y rampa de ambulancias (Vehicle and ambulance access)",
                    "m2",
                    1500,
                    135.00,
                    {"masterformat": "32 12 16"},
                ),
            ],
        ),
    ],
    markups=[
        ("Gastos generales", 9.0, "overhead", "direct_cost"),
        ("Utilidad", 8.0, "profit", "direct_cost"),
        ("IGV (18 %)", 18.0, "tax", "cumulative"),
    ],
    total_months=16,
    tender_name="Contrato de Obra - Estructura y Arquitectura",
    tender_companies=[
        ("Constructora Altamira Sur", "concursos@altamira-sur.example", 0.98),
        ("Edificaciones Quebrada Norte", "licitaciones@quebrada-norte.example", 1.04),
        ("Ingeniería y Obras Cordillera", "concursos@cordillera-obras.example", 1.01),
    ],
    tender_packages=[
        (
            "Contrato de Obra - Estructura y Arquitectura",
            "Movimiento de tierras, estructura de concreto armado, cobertura y acabados.",
            "evaluating",
            [
                ("Constructora Altamira Sur", "concursos@altamira-sur.example", 0.98),
                ("Edificaciones Quebrada Norte", "licitaciones@quebrada-norte.example", 1.04),
                ("Ingeniería y Obras Cordillera", "concursos@cordillera-obras.example", 1.01),
            ],
        ),
        (
            "Instalaciones Eléctricas, Mecánicas y Médicas",
            "Instalaciones eléctricas, climatización, gases medicinales, ascensores y detección de incendio.",
            "issued",
            [
                ("Instalaciones Integrales Pampa", "concursos@pampa-integrales.example", 0.99),
                ("Montajes y Sistemas Vilcanota", "licitaciones@vilcanota-montajes.example", 1.05),
            ],
        ),
    ],
    progress_claims=(0.10, 0.24, 0.41),
    claim_retention=0.10,
    project_metadata={
        "address": "Av. Camino Real 1450, San Isidro, 15036 Lima, Perú",
        "client": "Clínica Privada Mirador Andino S.A.C.",
        "architect": "Estudio de Arquitectura Huayna",
        "structural_engineer": "Ingeniería Estructural Sacsayhuamán",
        "gfa_m2": 6500,
        "site_area_m2": 2600,
        "storeys": 6,
        "basement_levels": 1,
        "beds": 120,
        "operating_theatres": 6,
        "construction_standards": [
            "Reglamento Nacional de Edificaciones (RNE)",
            "Norma Técnica E.030 Diseño Sismorresistente",
            "Norma Técnica A.050 Salud",
        ],
        "estimating_method": "Presupuesto por partidas con gastos generales, utilidad e IGV",
        "contract": "Contrato de obra a suma alzada con valorizaciones mensuales",
        "igv_note": (
            "Todos los precios son sin IGV. El IGV del 18 por ciento (16 por ciento de IGV más 2 por ciento "
            "de Impuesto de Promoción Municipal) se aplica como línea aparte."
        ),
        "valuation_note": (
            "Cada valorización mensual retiene el 10 por ciento como garantía de fiel cumplimiento; la factura "
            "de construcción lleva la detracción del 4 por ciento."
        ),
    },
    einvoice_showcase={
        "buyer_contact": {
            "legal_name": "Clínica Privada Mirador Andino S.A.C.",
            "vat_number": "20605991441",
            "address": {"street": "Av. Camino Real 1450, San Isidro", "city": "Lima", "postcode": "15036"},
        },
        "invoice": {
            "invoice_number": "F001-00000014",
            "notes": "Valorización N° 2 - Estructura, platea y placas",
            "line_items": [
                {
                    "description": "Valorización N° 2, movimiento de tierras y platea de cimentación",
                    "quantity": "1",
                    "unit": "lsum",
                    "unit_rate": "1850400.00",
                    "amount": "1850400.00",
                },
                {
                    "description": "Valorización N° 2, columnas y placas del sótano",
                    "quantity": "1",
                    "unit": "lsum",
                    "unit_rate": "962750.00",
                    "amount": "962750.00",
                },
            ],
        },
        "einvoice": {
            "vat_rate": "18",
            "seller": {
                "name": "Constructora Altamira Sur S.A.C.",
                "vat_id": "PE20604812373",
                "country_code": "PE",
                "line1": "Av. Javier Prado Este 4200",
                "postcode": "15023",
                "city": "Lima",
            },
            "pe_detraction": True,
            "pe_detraction_code": "030",
            "pe_detraction_percent": "4",
            "pe_detraction_account": "00-000-123456",
            "payment_terms": "Crédito a 30 días desde la aprobación de la valorización",
        },
    },
)
