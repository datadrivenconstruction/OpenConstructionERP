# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: mexico-mx - Conjunto Residencial, Monterrey, Nuevo Leon
# ---------------------------------------------------------------------------
# Presupuesto de obra (catalogo de conceptos) con el metodo mexicano de
# Analisis de Precios Unitarios (APU) para un conjunto residencial de dos
# torres de departamentos con amenidades en la zona de Cumbres, Monterrey,
# Nuevo Leon. A diferencia de la torre de uso mixto de la Ciudad de Mexico,
# este es un desarrollo de vivienda residencial media en un terreno de mejor
# capacidad de carga (cimentacion somera con zapatas y contratrabes) y clima
# calido, por lo que el aire acondicionado y el aislamiento pesan mas.
#
# Estructura de concreto reforzado con marcos, disenada conforme al Reglamento
# de Construcciones del municipio y a las normas aplicables. Precios a nivel
# Monterrey 2026 en pesos mexicanos (MXN), sin IVA. La clasificacion de
# plataforma se lleva en CSI MasterFormat (el estandar que entiende el
# instalador de demos) y la partida mexicana se conserva bajo la llave
# "mexico". Terminologia comun de obra: zapatas, contratrabes, castillos,
# dalas, cimbra, aplanado, block, tablaroca, tirol.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-monterrey",
    project_name="Conjunto Residencial Cumbres - Monterrey, Nuevo Leon",
    project_description=(
        "Construcción de un conjunto residencial de dos torres de "
        "departamentos de 12 niveles cada una, con casa club, alberca y "
        "estacionamiento, en la zona de Cumbres, Monterrey, Nuevo Leon. "
        "Alrededor de 180 viviendas. Estructura de concreto reforzado con "
        "marcos, cimentación somera de zapatas aisladas y corridas con "
        "contratrabes por la buena capacidad de carga del terreno. Envolvente "
        "con muros de block, aplanados y acabado de fachada tipo tirol, "
        "canceleria de aluminio y aire acondicionado tipo minisplit por el "
        "clima calido de la region. Precios a nivel Monterrey 2026 en pesos "
        "mexicanos, elaborados por precios unitarios (APU). Área construida "
        "cercana a 22,000 m2; costo directo de obra del orden de 400 millones "
        "de pesos, antes de IVA e indirectos."
    ),
    region="MX",
    classification_standard="masterformat",
    currency="MXN",
    locale="es-MX",
    address={
        "street": "Avenida Paseo de los Leones 2500, Cumbres",
        "city": "Monterrey",
        "postcode": "64619",
        "country": "Mexico",
        "lat": 25.7217,
        "lng": -100.4045,
    },
    validation_rule_sets=["mexico", "boq_quality", "project_completeness"],
    boq_name="Catalogo de Conceptos - Precios Unitarios (APU)",
    boq_description=(
        "Catalogo de conceptos por partidas conforme a la practica mexicana, "
        "integrado con analisis de precios unitarios (APU). Precios a nivel "
        "Monterrey 2026 (MXN), sin IVA; los indirectos, financiamiento y "
        "utilidad se aplican como sobrecostos."
    ),
    boq_metadata={
        "standard": "Analisis de Precios Unitarios (APU) - LOPSRM + division-based classification",
        "phase": "Proyecto ejecutivo - presupuesto de obra",
        "base_date": "2026-Q1",
        "price_level": "Monterrey 2026 (MXN, sin IVA)",
    },
    sections=[
        # 01 Preliminares y obra provisional
        (
            "01",
            "01 - Preliminares y Obra Provisional (Preliminaries / site setup)",
            {"masterformat": "01", "mexico": "Preliminares"},
            [
                ("01.001", "Limpia, desmonte y trazo con nivelación del terreno (Clearing & setting out)", "m2", 6500, 22.00, {"masterformat": "31 11 00", "mexico": "Preliminares"}),
                ("01.002", "Cerca de obra y control de acceso (Site hoarding)", "m", 380, 480.00, {"masterformat": "01 56 00", "mexico": "Preliminares"}),
                ("01.003", "Oficinas, almacen y sanitarios provisionales (Site offices)", "m2", 260, 3850.00, {"masterformat": "01 52 00", "mexico": "Preliminares"}),
                ("01.004", "Instalaciones provisionales de agua, drenaje y energia (Temporary services)", "lsum", 1, 320000.00, {"masterformat": "01 51 00", "mexico": "Preliminares"}),
                ("01.005", "Renta de grua y equipo de izaje (Crane & lifting rental)", "mes", 16, 165000.00, {"masterformat": "01 54 00", "mexico": "Equipo"}),
                ("01.006", "Residencia y supervision de obra (Site management)", "mes", 20, 240000.00, {"masterformat": "01 31 00", "mexico": "Indirectos"}),
                ("01.007", "Programa de seguridad e higiene NOM-031-STPS (Site safety)", "lsum", 1, 480000.00, {"masterformat": "01 35 29", "mexico": "Seguridad"}),
                ("01.008", "Seguros de obra y fianzas de cumplimiento (Insurance & bonds)", "lsum", 1, 850000.00, {"masterformat": "01 21 00", "mexico": "Indirectos"}),
                ("01.009", "Limpieza continua y retiro de escombro (Continuous cleaning)", "mes", 20, 28000.00, {"masterformat": "01 74 00", "mexico": "Preliminares"}),
            ],
        ),
        # 02 Cimentacion y terracerias
        (
            "02",
            "02 - Cimentación y Terracerias (Foundation & earthworks)",
            {"masterformat": "31", "mexico": "Cimentación"},
            [
                ("02.001", "Excavación con maquinaria para cimentación (Machine excavation)", "m3", 18500, 135.00, {"masterformat": "31 23 16", "mexico": "Cimentación"}),
                ("02.002", "Relleno compactado y mejoramiento de terreno (Compacted fill)", "m3", 8200, 245.00, {"masterformat": "31 23 23", "mexico": "Cimentación"}),
                ("02.003", "Plantilla de concreto f'c=100 kg/cm2 (Blinding concrete)", "m2", 3400, 155.00, {"masterformat": "03 30 00", "mexico": "Cimentación"}),
                ("02.004", "Zapatas aisladas y corridas f'c=250 kg/cm2 (Isolated & strip footings)", "m3", 1850, 3450.00, {"masterformat": "03 31 00", "mexico": "Cimentación"}),
                ("02.005", "Contratrabes de concreto f'c=250 kg/cm2 (Foundation tie beams)", "m3", 980, 3850.00, {"masterformat": "03 31 00", "mexico": "Cimentación"}),
                ("02.006", "Losa de cimentación en torres f'c=250 kg/cm2 (Foundation slab)", "m3", 1650, 3650.00, {"masterformat": "03 31 00", "mexico": "Cimentación"}),
                ("02.007", "Acero de refuerzo fy=4200 kg/cm2 en cimentación (Foundation rebar)", "t", 420, 38500.00, {"masterformat": "03 21 00", "mexico": "Cimentación"}),
                ("02.008", "Impermeabilización de cimentación y muros de contacto (Foundation waterproofing)", "m2", 3800, 285.00, {"masterformat": "07 13 00", "mexico": "Cimentación"}),
                ("02.009", "Firme de concreto en planta baja f'c=150 kg/cm2 (Ground-floor slab)", "m2", 4200, 245.00, {"masterformat": "03 53 00", "mexico": "Cimentación"}),
            ],
        ),
        # 03 Estructura de concreto reforzado
        (
            "03",
            "03 - Estructura de Concreto Reforzado (Reinforced concrete structure)",
            {"masterformat": "03", "mexico": "Estructura"},
            [
                ("03.001", "Columnas de concreto reforzado f'c=300 kg/cm2 (RC columns)", "m3", 1650, 4350.00, {"masterformat": "03 30 00", "mexico": "Estructura"}),
                ("03.002", "Muros de concreto y castillos ahogados f'c=250 (RC walls)", "m3", 1250, 4150.00, {"masterformat": "03 30 00", "mexico": "Estructura"}),
                ("03.003", "Losas macizas y aligeradas f'c=250 kg/cm2 (Solid & lightened slabs)", "m3", 4200, 3650.00, {"masterformat": "03 30 00", "mexico": "Estructura"}),
                ("03.004", "Trabes y vigas de concreto f'c=250 kg/cm2 (Beams)", "m3", 1450, 3950.00, {"masterformat": "03 30 00", "mexico": "Estructura"}),
                ("03.005", "Escaleras y rampas de concreto reforzado (Stairs & ramps)", "m3", 380, 4250.00, {"masterformat": "03 30 00", "mexico": "Estructura"}),
                ("03.006", "Acero de refuerzo fy=4200 kg/cm2 en superestructura (Rebar)", "t", 2200, 39500.00, {"masterformat": "03 21 00", "mexico": "Estructura"}),
                ("03.007", "Cimbra en columnas y muros (Column & wall formwork)", "m2", 12000, 385.00, {"masterformat": "03 11 00", "mexico": "Estructura"}),
                ("03.008", "Cimbra en losas, trabes y escaleras (Slab & beam formwork)", "m2", 28000, 365.00, {"masterformat": "03 11 13", "mexico": "Estructura"}),
                ("03.009", "Malla electrosoldada 6x6-10/10 en firmes y losas (Welded wire mesh)", "m2", 16000, 78.00, {"masterformat": "03 22 00", "mexico": "Estructura"}),
                ("03.010", "Concreto premezclado adicional bombeado (Additional ready-mix concrete)", "m3", 850, 3550.00, {"masterformat": "03 31 00", "mexico": "Estructura"}),
                ("03.011", "Curado, aditivos y pruebas de laboratorio (Curing & lab tests)", "lsum", 1, 480000.00, {"masterformat": "03 05 00", "mexico": "Estructura"}),
            ],
        ),
        # 04 Albanileria y muros
        (
            "04",
            "04 - Albanileria y Muros (Masonry & walls)",
            {"masterformat": "04", "mexico": "Albanileria"},
            [
                ("04.001", "Muros de block de concreto de 15cm (Concrete block walls)", "m2", 22000, 525.00, {"masterformat": "04 22 00", "mexico": "Albanileria"}),
                ("04.002", "Muros divisorios de tablaroca con bastidor metálico (Drywall partitions)", "m2", 9800, 565.00, {"masterformat": "09 29 00", "mexico": "Albanileria"}),
                ("04.003", "Castillos, dalas y cadenas de cerramiento (RC ties & bond beams)", "m", 14000, 175.00, {"masterformat": "04 05 00", "mexico": "Albanileria"}),
                ("04.004", "Aplanado de mortero en muros interiores (Internal plaster / render)", "m2", 38000, 210.00, {"masterformat": "09 24 00", "mexico": "Albanileria"}),
                ("04.005", "Aplanado y repellado en fachadas (External render)", "m2", 12000, 265.00, {"masterformat": "09 24 00", "mexico": "Albanileria"}),
                ("04.006", "Firmes y boquillas de albanileria (Screeds & reveals)", "m2", 14000, 165.00, {"masterformat": "03 53 00", "mexico": "Albanileria"}),
                ("04.007", "Impermeabilizante integral en morteros de zonas humedas (Water-repellent mortar)", "m2", 4200, 95.00, {"masterformat": "07 19 00", "mexico": "Albanileria"}),
                ("04.008", "Recubrimiento de fachada tipo tirol planchado (Textured facade finish)", "m2", 12000, 145.00, {"masterformat": "09 24 00", "mexico": "Albanileria"}),
                ("04.009", "Molduras, cornisas y remates de fachada (Facade trims)", "m", 3200, 185.00, {"masterformat": "09 24 00", "mexico": "Albanileria"}),
            ],
        ),
        # 05 Instalacion hidrosanitaria
        (
            "05",
            "05 - Instalación Hidrosanitaria (Plumbing & drainage)",
            {"masterformat": "22", "mexico": "Hidrosanitaria"},
            [
                ("05.001", "Red de agua fria en tuberia CPVC (Cold-water piping)", "m", 12000, 245.00, {"masterformat": "22 11 16", "mexico": "Hidrosanitaria"}),
                ("05.002", "Red de agua caliente con aislamiento (Hot-water piping)", "m", 6800, 345.00, {"masterformat": "22 11 23", "mexico": "Hidrosanitaria"}),
                ("05.003", "Red de drenaje sanitario en tuberia PVC (Sanitary drainage)", "m", 9800, 285.00, {"masterformat": "22 13 16", "mexico": "Hidrosanitaria"}),
                ("05.004", "Red de drenaje pluvial en tuberia PVC (Storm drainage)", "m", 4200, 320.00, {"masterformat": "22 14 00", "mexico": "Hidrosanitaria"}),
                ("05.005", "Cisterna de concreto y equipo hidroneumatico (Cistern & pressure system)", "lsum", 1, 1650000.00, {"masterformat": "22 11 00", "mexico": "Hidrosanitaria"}),
                ("05.006", "Muebles sanitarios y griferia de bajo consumo (Sanitary fixtures & taps)", "pcs", 720, 5850.00, {"masterformat": "22 40 00", "mexico": "Hidrosanitaria"}),
                ("05.007", "Calentadores solares de agua (Solar water heaters)", "pcs", 180, 16500.00, {"masterformat": "22 33 00", "mexico": "Hidrosanitaria"}),
                ("05.008", "Preparaciones para alberca y área humeda (Pool & wet-área rough-in)", "lsum", 1, 850000.00, {"masterformat": "13 11 00", "mexico": "Hidrosanitaria"}),
                ("05.009", "Conexion a la red municipal de agua y drenaje (Municipal connections)", "lsum", 1, 680000.00, {"masterformat": "33 10 00", "mexico": "Hidrosanitaria"}),
            ],
        ),
        # 06 Instalacion electrica
        (
            "06",
            "06 - Instalación Electrica (Electrical)",
            {"masterformat": "26", "mexico": "Electrica"},
            [
                ("06.001", "Acometida y equipo de medición (Service & metering)", "lsum", 1, 1850000.00, {"masterformat": "26 11 00", "mexico": "Electrica"}),
                ("06.002", "Tableros generales y de distribución (Main & distribution boards)", "pcs", 36, 58000.00, {"masterformat": "26 24 16", "mexico": "Electrica"}),
                ("06.003", "Canalizaciones y tuberia conduit (Conduit & raceways)", "m", 28000, 155.00, {"masterformat": "26 05 33", "mexico": "Electrica"}),
                ("06.004", "Cableado de fuerza y alumbrado (Power & lighting wiring)", "m", 62000, 88.00, {"masterformat": "26 05 19", "mexico": "Electrica"}),
                ("06.005", "Salidas electricas, contactos y apagadores (Outlets & switches)", "pcs", 6800, 345.00, {"masterformat": "26 27 26", "mexico": "Electrica"}),
                ("06.006", "Luminarias LED interiores y exteriores (LED luminaires)", "pcs", 4200, 850.00, {"masterformat": "26 51 00", "mexico": "Electrica"}),
                ("06.007", "Sistema de tierras fisicas y pararrayos (Earthing & lightning protection)", "lsum", 1, 620000.00, {"masterformat": "26 41 00", "mexico": "Electrica"}),
                ("06.008", "Cableado de voz, datos y television (Voice / data / TV cabling)", "lsum", 1, 1250000.00, {"masterformat": "27 10 00", "mexico": "Electrica"}),
                ("06.009", "Planta de emergencia y equipo de transferencia (Standby generator)", "pcs", 2, 1650000.00, {"masterformat": "26 32 13", "mexico": "Electrica"}),
            ],
        ),
        # 07 Instalacion mecanica y aire acondicionado
        (
            "07",
            "07 - Instalación Mecanica y Aire Acondicionado (Mechanical & HVAC)",
            {"masterformat": "23", "mexico": "Mecanica"},
            [
                ("07.001", "Minisplit inverter en departamentos (Split A/C units)", "pcs", 360, 22500.00, {"masterformat": "23 81 26", "mexico": "Mecanica"}),
                ("07.002", "Sistema de aire acondicionado en amenidades (Amenity HVAC)", "lsum", 1, 1450000.00, {"masterformat": "23 73 00", "mexico": "Mecanica"}),
                ("07.003", "Extracción y ventilación en estacionamiento (Parking ventilation)", "lsum", 1, 1250000.00, {"masterformat": "23 34 00", "mexico": "Mecanica"}),
                ("07.004", "Red de gas L.P. estacionario y regulación (LP gas system)", "lsum", 1, 980000.00, {"masterformat": "23 11 23", "mexico": "Mecanica"}),
                ("07.005", "Ductos y rejillas de ventilación (Ductwork & grilles)", "kg", 24000, 135.00, {"masterformat": "23 31 00", "mexico": "Mecanica"}),
                ("07.006", "Bombas, hidroneumatico y equipo mecanico (Pumps & mechanical plant)", "lsum", 1, 1450000.00, {"masterformat": "22 11 00", "mexico": "Mecanica"}),
                ("07.007", "Control y automatización de equipos (Controls & automation)", "lsum", 1, 850000.00, {"masterformat": "25 30 00", "mexico": "Mecanica"}),
            ],
        ),
        # 08 Acabados: pisos, muros, plafones y pintura
        (
            "08",
            "08 - Acabados: Pisos, Muros, Plafones y Pintura (Finishes & painting)",
            {"masterformat": "09", "mexico": "Acabados"},
            [
                ("08.001", "Piso de porcelanato en áreas comunes (Porcelain flooring)", "m2", 8200, 685.00, {"masterformat": "09 30 13", "mexico": "Acabados"}),
                ("08.002", "Piso laminado en departamentos (Laminate flooring)", "m2", 14500, 485.00, {"masterformat": "09 64 00", "mexico": "Acabados"}),
                ("08.003", "Piso de concreto pulido en estacionamiento (Polished concrete floor)", "m2", 12000, 245.00, {"masterformat": "03 35 00", "mexico": "Acabados"}),
                ("08.004", "Recubrimiento ceramico en banos y cocinas (Ceramic wall tiling)", "m2", 11500, 545.00, {"masterformat": "09 30 00", "mexico": "Acabados"}),
                ("08.005", "Plafon de tablaroca en departamentos (Gypsum board ceilings)", "m2", 18000, 385.00, {"masterformat": "09 29 00", "mexico": "Acabados"}),
                ("08.006", "Plafon reticular en áreas comunes (Suspended grid ceilings)", "m2", 4200, 465.00, {"masterformat": "09 51 00", "mexico": "Acabados"}),
                ("08.007", "Pintura vinílica en muros y plafones (Vinyl paint)", "m2", 62000, 88.00, {"masterformat": "09 91 00", "mexico": "Acabados"}),
                ("08.008", "Pintura de esmalte en herreria y detalles (Enamel paint)", "m2", 6800, 135.00, {"masterformat": "09 96 00", "mexico": "Acabados"}),
                ("08.009", "Recubrimiento epoxico en cuartos de maquinas (Epoxy coating)", "m2", 3200, 235.00, {"masterformat": "09 67 00", "mexico": "Acabados"}),
                ("08.010", "Zoclos, molduras y remates de acabado (Skirtings & trims)", "m", 12000, 95.00, {"masterformat": "09 60 00", "mexico": "Acabados"}),
                ("08.011", "Senaletica interior y numeración de viviendas (Signage & unit numbering)", "lsum", 1, 480000.00, {"masterformat": "10 14 00", "mexico": "Acabados"}),
            ],
        ),
        # 09 Canceleria, herreria y carpinteria
        (
            "09",
            "09 - Canceleria, Herreria y Carpinteria (Glazing, metalwork & joinery)",
            {"masterformat": "08", "mexico": "Canceleria"},
            [
                ("09.001", "Canceleria de aluminio y cristal en ventanas (Aluminium windows)", "m2", 8600, 2450.00, {"masterformat": "08 51 13", "mexico": "Canceleria"}),
                ("09.002", "Puertas de madera con marco y herrajes (Timber doors & hardware)", "pcs", 720, 5450.00, {"masterformat": "08 14 16", "mexico": "Carpinteria"}),
                ("09.003", "Puertas contra incendio certificadas (Fire-rated doors)", "pcs", 96, 11500.00, {"masterformat": "08 14 16", "mexico": "Carpinteria"}),
                ("09.004", "Cocinas integrales y closets (Fitted kitchens & closets)", "pcs", 360, 38500.00, {"masterformat": "12 35 30", "mexico": "Carpinteria"}),
                ("09.005", "Muebles de bano y cubiertas (Vanities & countertops)", "pcs", 420, 9850.00, {"masterformat": "12 35 70", "mexico": "Carpinteria"}),
                ("09.006", "Barandales de herreria y cristal en balcones (Balcony railings)", "m", 2400, 1450.00, {"masterformat": "05 52 00", "mexico": "Herreria"}),
                ("09.007", "Cerrajeria y control de acceso (Locksets & access control)", "pcs", 860, 1650.00, {"masterformat": "08 71 00", "mexico": "Herreria"}),
                ("09.008", "Porton, herreria exterior y rejas (Exterior metalwork & gates)", "lsum", 1, 850000.00, {"masterformat": "05 50 00", "mexico": "Herreria"}),
            ],
        ),
        # 10 Obra exterior, amenidades y limpieza
        (
            "10",
            "10 - Obra Exterior, Amenidades y Limpieza (External works, amenities & cleaning)",
            {"masterformat": "32", "mexico": "Obra exterior"},
            [
                ("10.001", "Pavimento de concreto en vialidades internas (Concrete paving)", "m2", 6800, 485.00, {"masterformat": "32 13 13", "mexico": "Obra exterior"}),
                ("10.002", "Guarniciones, banquetas y andadores (Kerbs & walkways)", "m", 2400, 365.00, {"masterformat": "32 16 13", "mexico": "Obra exterior"}),
                ("10.003", "Casa club, alberca y área de amenidades (Clubhouse & pool)", "lsum", 1, 8500000.00, {"masterformat": "13 11 00", "mexico": "Amenidades"}),
                ("10.004", "Áreas verdes, jardineria y riego (Landscaping & irrigation)", "m2", 4800, 485.00, {"masterformat": "32 90 00", "mexico": "Obra exterior"}),
                ("10.005", "Juegos infantiles y mobiliario exterior (Playground & site furniture)", "lsum", 1, 1250000.00, {"masterformat": "32 30 00", "mexico": "Amenidades"}),
                ("10.006", "Barda perimetral y caseta de vigilancia (Perimeter wall & gatehouse)", "m", 620, 2850.00, {"masterformat": "32 31 00", "mexico": "Obra exterior"}),
                ("10.007", "Alumbrado exterior y postes (External lighting)", "pcs", 120, 9850.00, {"masterformat": "26 56 00", "mexico": "Obra exterior"}),
                ("10.008", "Red exterior de drenaje y registros (External drainage & manholes)", "m", 2200, 545.00, {"masterformat": "33 40 00", "mexico": "Obra exterior"}),
                ("10.009", "Limpieza final, pruebas de operación y entrega (Final cleaning & handover)", "lsum", 1, 850000.00, {"masterformat": "01 74 00", "mexico": "Obra exterior"}),
            ],
        ),
    ],
    markups=[
        ("Indirectos de obra (overhead)", 11.0, "overhead", "direct_cost"),
        ("Financiamiento", 2.5, "overhead", "direct_cost"),
        ("Utilidad", 8.0, "profit", "direct_cost"),
        ("Cargos adicionales (SAT e inspección)", 0.7, "overhead", "direct_cost"),
        ("Contingencia de obra", 5.0, "contingency", "direct_cost"),
        ("IVA al 16 por ciento (SAT)", 16.0, "tax", "cumulative"),
    ],
    total_months=20,
    tender_name="Contrato de Obra a Precios Unitarios (Estructura y Albanileria)",
    tender_companies=[
        ("Constructora Duraval", "concursos@duraval.example", 0.98),
        ("Grupo Constructor Alcarno", "licitaciones@alcarno.example", 1.03),
        ("Edificaciones Trevanti", "concursos@trevanti.example", 1.01),
    ],
    tender_packages=[
        (
            "Contrato de Obra a Precios Unitarios (Estructura y Albanileria)",
            "Cimentación, estructura de concreto reforzado, albanileria y fachadas de las torres.",
            "evaluating",
            [
                ("Constructora Duraval", "concursos@duraval.example", 0.98),
                ("Grupo Constructor Alcarno", "licitaciones@alcarno.example", 1.03),
                ("Edificaciones Trevanti", "concursos@trevanti.example", 1.01),
            ],
        ),
        (
            "Instalaciones y Amenidades",
            "Instalación hidrosanitaria, electrica, aire acondicionado, casa club y alberca.",
            "issued",
            [
                ("Instalaciones Integrales Serranov", "concursos@serranov.example", 0.99),
                ("Electromecanica Sandoveral", "licitaciones@sandoveral.example", 1.04),
                ("Servicios y Montajes Verdalon", "concursos@verdalon.example", 1.02),
            ],
        ),
    ],
    project_metadata={
        "address": "Avenida Paseo de los Leones 2500, Cumbres, 64619 Monterrey, Nuevo Leon, Mexico",
        "client": "Inmobiliaria Altavela Residencial, S.A. de C.V.",
        "architect": "Estudio de Arquitectura Norvalle",
        "quantity_surveyor": "Costos y Presupuestos APU, S.C.",
        "structural_engineer": "Ingenieria Estructural Brandiz, S.C.",
        "gfa_m2": 22000,
        "site_área_m2": 9500,
        "storeys": 12,
        "towers": 2,
        "apartments": 180,
        "parking_spaces": 320,
        "construction_standards": [
            "Reglamento de Construcciones del municipio de Monterrey",
            "NTC para diseno y construcción de estructuras de concreto",
            "NOM-001-SEDE instalaciones electricas (utilización)",
            "NOM-020-ENER eficiencia energetica en edificaciones",
            "NOM-031-STPS seguridad en obras de construcción",
        ],
        "estimating_method": "Analisis de Precios Unitarios (APU) conforme a la LOPSRM y su reglamento",
        "regulator": "Municipio de Monterrey (licencia de construcción, Nuevo Leon)",
        "iva_note": "Todos los precios unitarios son sin IVA. El IVA del 16 por ciento (SAT) se aplica como cargo por separado.",
        "contract": "Contrato de obra a precios unitarios y tiempo determinado",
        "social_housing_note": "Vivienda residencial media; puede financiarse con credito hipotecario o INFONAVIT segun el comprador.",
    },
)
