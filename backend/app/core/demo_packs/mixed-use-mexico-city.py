# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: mexico-mx - Torre de Uso Mixto, Ciudad de Mexico
# ---------------------------------------------------------------------------
# Presupuesto de obra (catalogo de conceptos) elaborado con el metodo mexicano
# de Analisis de Precios Unitarios (APU) bajo la LOPSRM y su reglamento, para
# una torre vertical de uso mixto en Paseo de la Reforma, Ciudad de Mexico. El
# programa comprende 3 sotanos de estacionamiento, un podio comercial en planta
# baja (locales), 4 niveles de oficinas y 16 niveles de departamentos.
#
# Estructura de concreto reforzado con marcos y muros de cortante, disenada
# para zona sismica conforme al Reglamento de Construcciones para el Distrito
# Federal (RCDF) y sus Normas Tecnicas Complementarias (NTC-2017, sismo y
# concreto). Por tratarse de la Zona III (lacustre) del valle de Mexico la
# cimentacion es profunda: cajon de cimentacion con muro Milan perimetral y
# pilotes de friccion colados en sitio. Fachada de muro cortina modular con
# cristal de control solar.
#
# Los precios son a nivel Ciudad de Mexico 2026 en pesos mexicanos (MXN), sin
# incluir el IVA (16 por ciento, que se lleva como cargo por separado) ni los
# indirectos, financiamiento y utilidad, que se integran como sobrecostos APU.
# La clasificacion de plataforma se lleva en CSI MasterFormat (el estandar que
# entiende el instalador de demos) y la partida mexicana se conserva en cada
# concepto bajo la llave "mexico". La terminologia sigue el uso comun de obra
# en Mexico (castillos, dalas, cimbra, aplanado, plantilla, block, tablaroca).
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="mixed-use-mexico-city",
    project_name="Torre de Uso Mixto Reforma - Ciudad de Mexico",
    project_description=(
        "Construcción de una torre de uso mixto en Paseo de la Reforma, Ciudad "
        "de Mexico. 3 sotanos de estacionamiento, un podio comercial en planta "
        "baja con locales, 4 niveles de oficinas y 16 niveles de departamentos "
        "(alrededor de 190 viviendas). Estructura de concreto reforzado con "
        "marcos y muros de cortante, disenada para zona sismica conforme al "
        "Reglamento de Construcciones para el Distrito Federal (RCDF) y las "
        "Normas Tecnicas Complementarias (NTC-2017 de sismo y de concreto). "
        "Cimentación profunda por la Zona III (lacustre) del valle de Mexico: "
        "cajon de cimentación con muro Milan perimetral y pilotes de fricción "
        "colados en sitio. Fachada de muro cortina modular con cristal de "
        "control solar y planta de tratamiento con reuso de agua pluvial. "
        "Terreno de 2,800 m2 aproximados y área construida cercana a 38,000 m2. "
        "Presupuesto elaborado por precios unitarios (APU); costo directo de "
        "obra del orden de 835 millones de pesos, antes de IVA e indirectos."
    ),
    region="MX",
    classification_standard="masterformat",
    currency="MXN",
    locale="es-MX",
    address={
        "street": "Paseo de la Reforma 350, Cuauhtemoc",
        "city": "Ciudad de Mexico",
        "postcode": "06600",
        "country": "Mexico",
        "lat": 19.4270,
        "lng": -99.1677,
    },
    validation_rule_sets=["mexico", "boq_quality", "project_completeness"],
    boq_name="Catalogo de Conceptos - Precios Unitarios (APU)",
    boq_description=(
        "Catalogo de conceptos por partidas conforme a la practica mexicana, "
        "integrado con analisis de precios unitarios (APU) bajo la LOPSRM. "
        "Precios a nivel Ciudad de Mexico 2026 (MXN), sin IVA; los indirectos, "
        "financiamiento y utilidad se aplican como sobrecostos."
    ),
    boq_metadata={
        "standard": "Analisis de Precios Unitarios (APU) - LOPSRM + division-based classification",
        "phase": "Proyecto ejecutivo - presupuesto de obra",
        "base_date": "2026-Q1",
        "price_level": "Ciudad de Mexico 2026 (MXN, sin IVA)",
        "reglamento": "RCDF y Normas Tecnicas Complementarias (NTC-2017)",
    },
    sections=[
        # 01 Preliminares y obra provisional
        (
            "01",
            "01 - Preliminares y Obra Provisional (Preliminaries / site setup)",
            {"masterformat": "01", "mexico": "Preliminares"},
            [
                ("01.001", "Limpia, despalme y trazo con nivelación del terreno (Clearing & setting out)", "m2", 2800, 28.00, {"masterformat": "31 11 00", "mexico": "Preliminares"}),
                ("01.002", "Cerca perimetral de obra con lamina y postes (Site hoarding)", "m", 240, 620.00, {"masterformat": "01 56 00", "mexico": "Preliminares"}),
                ("01.003", "Oficinas de campo, almacen y sanitarios provisionales (Site offices)", "m2", 320, 4200.00, {"masterformat": "01 52 00", "mexico": "Preliminares"}),
                ("01.004", "Instalación provisional de agua, drenaje y energia electrica (Temporary services)", "lsum", 1, 480000.00, {"masterformat": "01 51 00", "mexico": "Preliminares"}),
                ("01.005", "Renta de grua torre con montaje y desmontaje (Tower crane)", "mes", 22, 240000.00, {"masterformat": "01 54 00", "mexico": "Equipo"}),
                ("01.006", "Renta de bomba estacionaria para concreto (Concrete pump rental)", "mes", 18, 85000.00, {"masterformat": "01 54 00", "mexico": "Equipo"}),
                ("01.007", "Dirección, residencia y supervision de obra (Site management)", "mes", 26, 320000.00, {"masterformat": "01 31 00", "mexico": "Indirectos"}),
                ("01.008", "Programa de seguridad e higiene NOM-031-STPS (Site safety)", "lsum", 1, 780000.00, {"masterformat": "01 35 29", "mexico": "Seguridad"}),
                ("01.009", "Señalización, seguros de obra y fianzas de cumplimiento (Insurance & bonds)", "lsum", 1, 1650000.00, {"masterformat": "01 21 00", "mexico": "Indirectos"}),
                ("01.010", "Limpieza continua y retiro de escombro a tiro autorizado (Continuous cleaning)", "mes", 26, 42000.00, {"masterformat": "01 74 00", "mexico": "Preliminares"}),
            ],
        ),
        # 02 Cimentacion profunda y sotanos
        (
            "02",
            "02 - Cimentación Profunda y Sotanos (Deep foundation & basements)",
            {"masterformat": "31", "mexico": "Cimentación"},
            [
                ("02.001", "Excavación masiva con maquinaria para 3 sotanos (Bulk excavation)", "m3", 42000, 145.00, {"masterformat": "31 23 16", "mexico": "Cimentación"}),
                ("02.002", "Muro Milan colado en sitio para contención perimetral (Slurry / diaphragm wall)", "m2", 6800, 6850.00, {"masterformat": "31 56 00", "mexico": "Cimentación"}),
                ("02.003", "Pilotes de fricción colados en sitio d=80cm (Bored friction piles)", "m", 5200, 2650.00, {"masterformat": "31 63 29", "mexico": "Cimentación"}),
                ("02.004", "Prueba de carga e integridad de pilotes (Pile load testing)", "lsum", 1, 620000.00, {"masterformat": "31 09 00", "mexico": "Cimentación"}),
                ("02.005", "Sistema de bombeo y abatimiento del nivel freatico (Dewatering)", "lsum", 1, 1450000.00, {"masterformat": "31 23 19", "mexico": "Cimentación"}),
                ("02.006", "Plantilla de concreto f'c=100 kg/cm2 bajo cimentación (Blinding concrete)", "m2", 2900, 165.00, {"masterformat": "03 30 00", "mexico": "Cimentación"}),
                ("02.007", "Losa de cimentación tipo cajon, concreto f'c=300 kg/cm2 (Foundation raft)", "m3", 3800, 3950.00, {"masterformat": "03 31 00", "mexico": "Cimentación"}),
                ("02.008", "Acero de refuerzo fy=4200 kg/cm2 en cimentación (Foundation rebar)", "t", 720, 38500.00, {"masterformat": "03 21 00", "mexico": "Cimentación"}),
                ("02.009", "Impermeabilización y sello de juntas en muros de sotano (Basement waterproofing)", "m2", 7200, 685.00, {"masterformat": "07 13 00", "mexico": "Cimentación"}),
            ],
        ),
        # 03 Estructura de concreto reforzado
        (
            "03",
            "03 - Estructura de Concreto Reforzado (Reinforced concrete structure)",
            {"masterformat": "03", "mexico": "Estructura"},
            [
                ("03.001", "Columnas de concreto reforzado f'c=350 kg/cm2 (RC columns)", "m3", 2600, 4650.00, {"masterformat": "03 30 00", "mexico": "Estructura"}),
                ("03.002", "Muros de cortante de concreto f'c=350 kg/cm2 (Shear walls)", "m3", 3100, 4250.00, {"masterformat": "03 30 00", "mexico": "Estructura"}),
                ("03.003", "Losas macizas y reticulares f'c=300 kg/cm2 (Solid & waffle slabs)", "m3", 6800, 3850.00, {"masterformat": "03 30 00", "mexico": "Estructura"}),
                ("03.004", "Trabes y vigas de concreto f'c=300 kg/cm2 (Beams)", "m3", 2400, 4100.00, {"masterformat": "03 30 00", "mexico": "Estructura"}),
                ("03.005", "Rampas y escaleras de concreto reforzado (Ramps & stairs)", "m3", 620, 4350.00, {"masterformat": "03 30 00", "mexico": "Estructura"}),
                ("03.006", "Acero de refuerzo fy=4200 kg/cm2 en superestructura (Rebar)", "t", 4200, 39500.00, {"masterformat": "03 21 00", "mexico": "Estructura"}),
                ("03.007", "Cimbra aparente en columnas y muros de cortante (Architectural formwork)", "m2", 18000, 520.00, {"masterformat": "03 11 00", "mexico": "Estructura"}),
                ("03.008", "Cimbra comun en losas, trabes y rampas (Common formwork)", "m2", 46000, 385.00, {"masterformat": "03 11 13", "mexico": "Estructura"}),
                ("03.009", "Concreto premezclado adicional bombeado (Additional ready-mix concrete)", "m3", 1200, 3650.00, {"masterformat": "03 31 00", "mexico": "Estructura"}),
                ("03.010", "Malla electrosoldada 6x6-10/10 en firmes (Welded wire mesh)", "m2", 22000, 78.00, {"masterformat": "03 22 00", "mexico": "Estructura"}),
                ("03.011", "Aditivos, curado y pruebas de laboratorio de concreto (Curing & lab tests)", "lsum", 1, 980000.00, {"masterformat": "03 05 00", "mexico": "Estructura"}),
                ("03.012", "Postensado en losas de claros largos, torones y anclajes (Post-tensioning)", "t", 145, 62000.00, {"masterformat": "03 38 00", "mexico": "Estructura"}),
            ],
        ),
        # 04 Estructura metalica y elementos de acero
        (
            "04",
            "04 - Estructura Metálica y Elementos de Acero (Structural steel & metalwork)",
            {"masterformat": "05", "mexico": "Estructura metálica"},
            [
                ("04.001", "Estructura metálica en cubiertas y volados (Structural steel)", "t", 185, 52000.00, {"masterformat": "05 12 00", "mexico": "Estructura metálica"}),
                ("04.002", "Escaleras metálicas de emergencia galvanizadas (Steel escape stairs)", "pcs", 6, 165000.00, {"masterformat": "05 51 00", "mexico": "Herreria"}),
                ("04.003", "Recubrimiento intumescente contra fuego en acero (Intumescent fire coating)", "m2", 3200, 420.00, {"masterformat": "05 05 23", "mexico": "Estructura metálica"}),
                ("04.004", "Barandales y pasamanos metálicos en escaleras (Handrails & balustrades)", "m", 1250, 1850.00, {"masterformat": "05 52 00", "mexico": "Herreria"}),
                ("04.005", "Galvanizado y pintura de protección en acero (Galvanizing & protective coating)", "t", 185, 9500.00, {"masterformat": "05 05 13", "mexico": "Estructura metálica"}),
                ("04.006", "Elementos de herreria estructural diversos (Sundry structural metalwork)", "lsum", 1, 1250000.00, {"masterformat": "05 50 00", "mexico": "Herreria"}),
            ],
        ),
        # 05 Albanileria y muros divisorios
        (
            "05",
            "05 - Albanileria y Muros Divisorios (Masonry & partitions)",
            {"masterformat": "04", "mexico": "Albanileria"},
            [
                ("05.001", "Muros de block de concreto de 15cm asentados con mortero (Concrete block walls)", "m2", 16500, 545.00, {"masterformat": "04 22 00", "mexico": "Albanileria"}),
                ("05.002", "Muros divisorios de tabique rojo recocido (Clay brick partitions)", "m2", 8200, 620.00, {"masterformat": "04 21 13", "mexico": "Albanileria"}),
                ("05.003", "Muros divisorios de tablaroca con bastidor metálico (Drywall partitions)", "m2", 14500, 585.00, {"masterformat": "09 29 00", "mexico": "Albanileria"}),
                ("05.004", "Castillos, dalas y cadenas de cerramiento de concreto (RC ties & bond beams)", "m", 12000, 185.00, {"masterformat": "04 05 00", "mexico": "Albanileria"}),
                ("05.005", "Aplanado de mortero cemento-arena en muros (Cement plaster / render)", "m2", 42000, 220.00, {"masterformat": "09 24 00", "mexico": "Albanileria"}),
                ("05.006", "Firmes de concreto f'c=150 kg/cm2 en pisos (Floor screed)", "m2", 22000, 245.00, {"masterformat": "03 53 00", "mexico": "Albanileria"}),
                ("05.007", "Boquillas, remates y molduras de albanileria (Reveals & trims)", "m", 6800, 145.00, {"masterformat": "09 24 00", "mexico": "Albanileria"}),
                ("05.008", "Impermeabilizante integral en morteros de zonas humedas (Water-repellent mortar)", "m2", 5200, 95.00, {"masterformat": "07 19 00", "mexico": "Albanileria"}),
            ],
        ),
        # 06 Impermeabilizacion y azoteas
        (
            "06",
            "06 - Impermeabilización y Azoteas (Waterproofing & roofing)",
            {"masterformat": "07", "mexico": "Impermeabilización"},
            [
                ("06.001", "Impermeabilización prefabricada en azoteas, 2 capas (Roof waterproofing)", "m2", 3200, 385.00, {"masterformat": "07 52 00", "mexico": "Impermeabilización"}),
                ("06.002", "Aislamiento termico en azotea con poliestireno (Roof thermal insulation)", "m2", 3200, 265.00, {"masterformat": "07 22 00", "mexico": "Impermeabilización"}),
                ("06.003", "Relleno de pendientes y entortado en azoteas (Screed to falls)", "m2", 3200, 185.00, {"masterformat": "03 53 00", "mexico": "Impermeabilización"}),
                ("06.004", "Impermeabilización en banos y áreas humedas (Wet-área waterproofing)", "m2", 6800, 320.00, {"masterformat": "07 14 00", "mexico": "Impermeabilización"}),
                ("06.005", "Bajadas pluviales y coladeras de azotea (Rainwater downpipes & drains)", "m", 1450, 385.00, {"masterformat": "07 71 23", "mexico": "Impermeabilización"}),
                ("06.006", "Sellado de juntas de construcción y dilatación (Construction / movement joints)", "m", 2400, 165.00, {"masterformat": "07 92 00", "mexico": "Impermeabilización"}),
                ("06.007", "Barreras de vapor y protecciones en cubiertas (Vapor barriers & protection)", "m2", 3200, 125.00, {"masterformat": "07 26 00", "mexico": "Impermeabilización"}),
            ],
        ),
        # 07 Canceleria, fachada y vidrio
        (
            "07",
            "07 - Canceleria, Fachada y Vidrio (Curtain wall, glazing & doors)",
            {"masterformat": "08", "mexico": "Canceleria"},
            [
                ("07.001", "Muro cortina modular con cristal de control solar (Unitized curtain wall)", "m2", 9800, 6850.00, {"masterformat": "08 44 00", "mexico": "Canceleria"}),
                ("07.002", "Canceleria de aluminio en ventanas de departamentos (Aluminium windows)", "m2", 5600, 2650.00, {"masterformat": "08 51 13", "mexico": "Canceleria"}),
                ("07.003", "Cristal templado en barandales y domos (Tempered glass)", "m2", 1450, 1850.00, {"masterformat": "08 80 00", "mexico": "Canceleria"}),
                ("07.004", "Fachada ventilada con panel composite de aluminio (ACP ventilated facade)", "m2", 4200, 2850.00, {"masterformat": "07 42 43", "mexico": "Fachada"}),
                ("07.005", "Puertas automaticas de cristal en accesos (Automatic glass doors)", "pcs", 6, 165000.00, {"masterformat": "08 42 29", "mexico": "Canceleria"}),
                ("07.006", "Domos y tragaluces de policarbonato (Polycarbonate skylights)", "m2", 480, 2450.00, {"masterformat": "08 63 00", "mexico": "Canceleria"}),
                ("07.007", "Cancel de aluminio y cristal en locales comerciales (Shopfront glazing)", "m2", 1250, 4250.00, {"masterformat": "08 43 00", "mexico": "Canceleria"}),
                ("07.008", "Persianas, celosias y parasoles de fachada (Louvres & sun shading)", "m2", 1850, 1650.00, {"masterformat": "10 71 13", "mexico": "Fachada"}),
            ],
        ),
        # 08 Instalacion hidrosanitaria
        (
            "08",
            "08 - Instalación Hidrosanitaria (Plumbing & drainage)",
            {"masterformat": "22", "mexico": "Hidrosanitaria"},
            [
                ("08.001", "Red de agua fria en tuberia CPVC (Cold-water piping)", "m", 9800, 285.00, {"masterformat": "22 11 16", "mexico": "Hidrosanitaria"}),
                ("08.002", "Red de agua caliente con aislamiento (Hot-water piping)", "m", 5200, 385.00, {"masterformat": "22 11 23", "mexico": "Hidrosanitaria"}),
                ("08.003", "Red de drenaje sanitario en tuberia PVC (Sanitary drainage)", "m", 8400, 345.00, {"masterformat": "22 13 16", "mexico": "Hidrosanitaria"}),
                ("08.004", "Red de drenaje pluvial en tuberia PVC (Storm drainage)", "m", 3600, 385.00, {"masterformat": "22 14 00", "mexico": "Hidrosanitaria"}),
                ("08.005", "Cisterna de concreto y equipo hidroneumatico (Cistern & pressure system)", "lsum", 1, 2850000.00, {"masterformat": "22 11 00", "mexico": "Hidrosanitaria"}),
                ("08.006", "Muebles sanitarios y griferia de bajo consumo (Sanitary fixtures & taps)", "pcs", 780, 6850.00, {"masterformat": "22 40 00", "mexico": "Hidrosanitaria"}),
                ("08.007", "Calentadores solares y de paso (Solar & instant water heaters)", "pcs", 96, 18500.00, {"masterformat": "22 33 00", "mexico": "Hidrosanitaria"}),
                ("08.008", "Planta de tratamiento de aguas residuales (Wastewater treatment plant)", "lsum", 1, 3450000.00, {"masterformat": "22 13 00", "mexico": "Hidrosanitaria"}),
                ("08.009", "Sistema de captación y reuso de agua pluvial (Rainwater harvesting)", "lsum", 1, 1250000.00, {"masterformat": "22 13 53", "mexico": "Hidrosanitaria"}),
            ],
        ),
        # 09 Instalacion electrica y voz-datos
        (
            "09",
            "09 - Instalación Electrica y Voz-Datos (Electrical & ICT)",
            {"masterformat": "26", "mexico": "Electrica"},
            [
                ("09.001", "Acometida y subestación electrica compacta (Substation & service)", "lsum", 1, 5850000.00, {"masterformat": "26 11 00", "mexico": "Electrica"}),
                ("09.002", "Tableros generales y de distribución por nivel (Main & distribution boards)", "pcs", 48, 68000.00, {"masterformat": "26 24 16", "mexico": "Electrica"}),
                ("09.003", "Canalizaciones, tuberia conduit y charolas (Conduit & cable trays)", "m", 42000, 165.00, {"masterformat": "26 05 33", "mexico": "Electrica"}),
                ("09.004", "Cableado de fuerza y alumbrado (Power & lighting wiring)", "m", 88000, 95.00, {"masterformat": "26 05 19", "mexico": "Electrica"}),
                ("09.005", "Salidas electricas, contactos y apagadores (Outlets & switches)", "pcs", 8600, 385.00, {"masterformat": "26 27 26", "mexico": "Electrica"}),
                ("09.006", "Luminarias LED en interiores y áreas comunes (LED luminaires)", "pcs", 6800, 985.00, {"masterformat": "26 51 00", "mexico": "Electrica"}),
                ("09.007", "Planta de emergencia diesel y equipo de transferencia (Standby generator)", "pcs", 2, 2850000.00, {"masterformat": "26 32 13", "mexico": "Electrica"}),
                ("09.008", "Sistema de tierras fisicas y pararrayos (Earthing & lightning protection)", "lsum", 1, 985000.00, {"masterformat": "26 41 00", "mexico": "Electrica"}),
                ("09.009", "Cableado estructurado de voz y datos (Structured cabling)", "lsum", 1, 3200000.00, {"masterformat": "27 10 00", "mexico": "Electrica"}),
                ("09.010", "Paneles solares fotovoltaicos en azotea con inversores (Rooftop solar PV)", "lsum", 1, 4850000.00, {"masterformat": "48 14 00", "mexico": "Electrica"}),
            ],
        ),
        # 10 Instalacion mecanica, HVAC y aire acondicionado
        (
            "10",
            "10 - Instalación Mecanica y Aire Acondicionado (Mechanical & HVAC)",
            {"masterformat": "23", "mexico": "Mecanica"},
            [
                ("10.001", "Unidades manejadoras de aire en oficinas (Air-handling units)", "pcs", 18, 285000.00, {"masterformat": "23 73 00", "mexico": "Mecanica"}),
                ("10.002", "Minisplit inverter en departamentos (Split A/C units)", "pcs", 220, 24500.00, {"masterformat": "23 81 26", "mexico": "Mecanica"}),
                ("10.003", "Ductos de lamina galvanizada con aislamiento (Insulated ductwork)", "kg", 78000, 145.00, {"masterformat": "23 31 00", "mexico": "Mecanica"}),
                ("10.004", "Sistema de extracción y ventilación en sotanos (Basement ventilation)", "lsum", 1, 2450000.00, {"masterformat": "23 34 00", "mexico": "Mecanica"}),
                ("10.005", "Presurización de escaleras de emergencia (Stair pressurization)", "pcs", 4, 285000.00, {"masterformat": "23 34 23", "mexico": "Mecanica"}),
                ("10.006", "Red de agua helada y bombas (Chilled-water piping & pumps)", "m", 3200, 685.00, {"masterformat": "23 21 13", "mexico": "Mecanica"}),
                ("10.007", "Sistema de gas L.P. estacionario y regulación (LP gas system)", "lsum", 1, 1250000.00, {"masterformat": "23 11 23", "mexico": "Mecanica"}),
                ("10.008", "Control automatico y monitoreo de instalaciones (BMS controls)", "lsum", 1, 2850000.00, {"masterformat": "25 30 00", "mexico": "Mecanica"}),
            ],
        ),
        # 11 Sistemas contra incendio y transporte vertical
        (
            "11",
            "11 - Contra Incendio y Transporte Vertical (Fire protection & lifts)",
            {"masterformat": "21", "mexico": "Contra incendio"},
            [
                ("11.001", "Red de rociadores automaticos contra incendio (Sprinkler system)", "m2", 32000, 265.00, {"masterformat": "21 13 13", "mexico": "Contra incendio"}),
                ("11.002", "Hidrantes, mangueras y cisterna contra incendio (Hydrants & fire tank)", "lsum", 1, 1850000.00, {"masterformat": "21 12 00", "mexico": "Contra incendio"}),
                ("11.003", "Detección de humo y alarma direccionable (Fire detection & alarm)", "m2", 32000, 145.00, {"masterformat": "28 31 00", "mexico": "Contra incendio"}),
                ("11.004", "Supresion por agente limpio en cuartos de sistemas (Clean-agent suppression)", "lsum", 1, 985000.00, {"masterformat": "21 22 00", "mexico": "Contra incendio"}),
                ("11.005", "Elevadores de pasajeros de alta velocidad (High-speed passenger lifts)", "pcs", 6, 2950000.00, {"masterformat": "14 21 00", "mexico": "Elevadores"}),
                ("11.006", "Elevador de carga y montacargas (Goods lift)", "pcs", 2, 2450000.00, {"masterformat": "14 20 00", "mexico": "Elevadores"}),
                ("11.007", "Circuito cerrado de television y control de acceso (CCTV & access control)", "lsum", 1, 3200000.00, {"masterformat": "28 20 00", "mexico": "Seguridad"}),
                ("11.008", "Escaleras electricas en el podio comercial (Escalators)", "pcs", 4, 1850000.00, {"masterformat": "14 31 00", "mexico": "Elevadores"}),
            ],
        ),
        # 12 Acabados: pisos, muros y plafones
        (
            "12",
            "12 - Acabados: Pisos, Muros y Plafones (Finishes: floors, walls, ceilings)",
            {"masterformat": "09", "mexico": "Acabados"},
            [
                ("12.001", "Piso de porcelanato en lobbies y locales comerciales (Porcelain flooring)", "m2", 16500, 785.00, {"masterformat": "09 30 13", "mexico": "Acabados"}),
                ("12.002", "Piso laminado y de ingenieria en departamentos (Engineered / laminate flooring)", "m2", 12800, 585.00, {"masterformat": "09 64 00", "mexico": "Acabados"}),
                ("12.003", "Piso de granito en accesos principales (Granite flooring)", "m2", 1450, 2850.00, {"masterformat": "09 63 40", "mexico": "Acabados"}),
                ("12.004", "Alfombra modular en oficinas (Carpet tiles)", "m2", 8600, 585.00, {"masterformat": "09 68 13", "mexico": "Acabados"}),
                ("12.005", "Recubrimiento ceramico en muros de banos y cocinas (Ceramic wall tiling)", "m2", 12500, 585.00, {"masterformat": "09 30 00", "mexico": "Acabados"}),
                ("12.006", "Plafon de tablaroca y de fibra mineral (Suspended ceilings)", "m2", 22000, 485.00, {"masterformat": "09 51 00", "mexico": "Acabados"}),
                ("12.007", "Pintura vinílica en muros y plafones (Vinyl paint)", "m2", 68000, 95.00, {"masterformat": "09 91 00", "mexico": "Acabados"}),
                ("12.008", "Pintura de esmalte y recubrimientos especiales (Enamel & special coatings)", "m2", 8600, 145.00, {"masterformat": "09 96 00", "mexico": "Acabados"}),
                ("12.009", "Recubrimiento epoxico en pisos de estacionamiento (Epoxy floor coating)", "m2", 22000, 245.00, {"masterformat": "09 67 00", "mexico": "Acabados"}),
                ("12.010", "Canceleria de tablaroca, marmol y detalles de lobby (Lobby finishes)", "lsum", 1, 2850000.00, {"masterformat": "09 77 00", "mexico": "Acabados"}),
                ("12.011", "Senaletica interior y sistema de identificación (Signage & wayfinding)", "lsum", 1, 985000.00, {"masterformat": "10 14 00", "mexico": "Acabados"}),
            ],
        ),
        # 13 Carpinteria, herreria y cerrajeria
        (
            "13",
            "13 - Carpinteria, Herreria y Cerrajeria (Joinery, metalwork & hardware)",
            {"masterformat": "06", "mexico": "Carpinteria"},
            [
                ("13.001", "Puertas de madera con marco y herrajes (Timber doors & hardware)", "pcs", 620, 5850.00, {"masterformat": "08 14 16", "mexico": "Carpinteria"}),
                ("13.002", "Puertas contra incendio certificadas en rutas de evacuación (Fire-rated doors)", "pcs", 145, 12500.00, {"masterformat": "08 14 16", "mexico": "Carpinteria"}),
                ("13.003", "Cocinas integrales y closets en departamentos (Fitted kitchens & closets)", "pcs", 220, 42000.00, {"masterformat": "12 35 30", "mexico": "Carpinteria"}),
                ("13.004", "Muebles de bano y cubiertas de cuarzo (Vanities & countertops)", "pcs", 320, 12500.00, {"masterformat": "12 35 70", "mexico": "Carpinteria"}),
                ("13.005", "Cancel y puertas de tambor en interiores (Interior flush doors)", "pcs", 480, 3850.00, {"masterformat": "08 14 00", "mexico": "Carpinteria"}),
                ("13.006", "Cerrajeria, control de acceso y chapas (Locksets & door hardware)", "pcs", 980, 1850.00, {"masterformat": "08 71 00", "mexico": "Carpinteria"}),
                ("13.007", "Barandales de herreria y cancel en escaleras (Stair railings & metalwork)", "m", 1250, 1650.00, {"masterformat": "05 52 13", "mexico": "Herreria"}),
            ],
        ),
        # 14 Obra exterior, urbanizacion y limpieza
        (
            "14",
            "14 - Obra Exterior, Urbanización y Limpieza (External works & cleaning)",
            {"masterformat": "32", "mexico": "Obra exterior"},
            [
                ("14.001", "Pavimento asfaltico en vialidades y rampas (Asphalt paving)", "m2", 4200, 485.00, {"masterformat": "32 12 16", "mexico": "Obra exterior"}),
                ("14.002", "Pavimento de concreto estampado en andadores (Stamped concrete paving)", "m2", 3200, 585.00, {"masterformat": "32 13 13", "mexico": "Obra exterior"}),
                ("14.003", "Guarniciones y banquetas de concreto (Kerbs & sidewalks)", "m", 1450, 385.00, {"masterformat": "32 16 13", "mexico": "Obra exterior"}),
                ("14.004", "Barda perimetral y control de acceso vehicular (Perimeter wall & gate)", "m", 320, 3850.00, {"masterformat": "32 31 00", "mexico": "Obra exterior"}),
                ("14.005", "Áreas verdes, jardineria y riego automatico (Landscaping & irrigation)", "m2", 2400, 585.00, {"masterformat": "32 90 00", "mexico": "Obra exterior"}),
                ("14.006", "Alumbrado exterior y postes (External lighting)", "pcs", 96, 12500.00, {"masterformat": "26 56 00", "mexico": "Obra exterior"}),
                ("14.007", "Red exterior de drenaje, registros y pozos de visita (External drainage & manholes)", "m", 1850, 685.00, {"masterformat": "33 40 00", "mexico": "Obra exterior"}),
                ("14.008", "Mobiliario urbano y señalización vial (Street furniture & signage)", "lsum", 1, 985000.00, {"masterformat": "32 33 00", "mexico": "Obra exterior"}),
                ("14.009", "Limpieza final, pruebas de operación y entrega (Final cleaning & commissioning)", "lsum", 1, 1250000.00, {"masterformat": "01 74 00", "mexico": "Obra exterior"}),
            ],
        ),
    ],
    markups=[
        ("Indirectos de obra (overhead)", 12.0, "overhead", "direct_cost"),
        ("Financiamiento", 2.5, "overhead", "direct_cost"),
        ("Utilidad", 8.0, "profit", "direct_cost"),
        ("Cargos adicionales (SAT e inspección)", 0.7, "overhead", "direct_cost"),
        ("Contingencia de obra", 5.0, "contingency", "direct_cost"),
        ("IVA al 16 por ciento (SAT)", 16.0, "tax", "cumulative"),
    ],
    total_months=28,
    tender_name="Contrato de Obra a Precios Unitarios (Estructura y Envolvente)",
    tender_companies=[
        ("Constructora Terrandia", "concursos@terrandia.example", 0.98),
        ("Grupo Constructor Velanda", "licitaciones@velanda.example", 1.04),
        ("Edificaciones Zarvella", "concursos@zarvella.example", 1.01),
    ],
    tender_packages=[
        (
            "Contrato de Obra a Precios Unitarios (Estructura y Envolvente)",
            "Cimentación profunda, estructura de concreto reforzado, fachada y muro cortina.",
            "evaluating",
            [
                ("Constructora Terrandia", "concursos@terrandia.example", 0.98),
                ("Grupo Constructor Velanda", "licitaciones@velanda.example", 1.04),
                ("Edificaciones Zarvella", "concursos@zarvella.example", 1.01),
            ],
        ),
        (
            "Instalaciones (Hidrosanitaria, Electrica y Mecanica)",
            "Instalación hidrosanitaria, electrica, voz-datos, mecanica, HVAC y energia solar.",
            "issued",
            [
                ("Instalaciones Integrales Serranov", "concursos@serranov.example", 0.99),
                ("Ingenieria y Montajes Calverte", "licitaciones@calverte.example", 1.05),
                ("Servicios Electromecanicos Nordeva", "concursos@nordeva.example", 1.02),
            ],
        ),
        (
            "Acabados y Fit-out",
            "Acabados de pisos, muros y plafones, carpinteria, canceleria interior y detalles.",
            "draft",
            [
                ("Acabados y Remodelaciones Verlanto", "concursos@verlanto.example", 0.97),
                ("Interiores y Acabados Mirlanda", "licitaciones@mirlanda.example", 1.06),
                ("Constructora Vallemar", "concursos@vallemar.example", 1.03),
            ],
        ),
    ],
    project_metadata={
        "address": "Paseo de la Reforma 350, Cuauhtemoc, 06600 Ciudad de Mexico, Mexico",
        "client": "Desarrolladora Sarvento 350, S.A. de C.V.",
        "architect": "Taller de Arquitectura Nublanto",
        "quantity_surveyor": "Costos y Presupuestos APU, S.C.",
        "structural_engineer": "Ingenieria Estructural Aldrevi, S.C.",
        "gfa_m2": 38000,
        "site_área_m2": 2800,
        "storeys": 20,
        "basement_levels": 3,
        "apartments": 190,
        "parking_spaces": 540,
        "construction_standards": [
            "Reglamento de Construcciones para el Distrito Federal (RCDF)",
            "NTC-2017 para diseno por sismo (Normas Tecnicas Complementarias)",
            "NTC para diseno y construcción de estructuras de concreto",
            "NOM-001-SEDE instalaciones electricas (utilización)",
            "NOM-020-ENER eficiencia energetica en edificaciones",
            "NOM-031-STPS seguridad en obras de construcción",
        ],
        "estimating_method": "Analisis de Precios Unitarios (APU) conforme a la LOPSRM y su reglamento",
        "regulator": "Alcaldia Cuauhtemoc y SEDUVI (licencia de construcción, Ciudad de Mexico)",
        "seismic_zone": "Zona III (lacustre) del valle de Mexico, diseno sismico NTC-2017",
        "iva_note": "Todos los precios unitarios son sin IVA. El IVA del 16 por ciento (SAT) se aplica como cargo por separado.",
        "contract": "Contrato de obra a precios unitarios y tiempo determinado",
        "social_housing_note": "Proyecto de vivienda residencial y uso mixto; no aplica financiamiento INFONAVIT/FOVISSSTE.",
    },
)
