# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: Edificio de uso mixto - Barcelona, Poblenou
# ---------------------------------------------------------------------------
# A Spanish presupuesto is a two-level document: capitulos (chapters) that
# follow the trade sequence, and partidas (items) inside them. The measured
# works total is the presupuesto de ejecucion material (PEM). Gastos generales
# and beneficio industrial are then taken on the PEM to give the presupuesto de
# ejecucion por contrata (PEC), and IVA is added last. The markups below are
# modelled exactly that way: both percentages apply to ``direct_cost``, not one
# on top of the other, and only the tax line is cumulative.
#
# WHAT IS SOURCED AND WHAT IS NOT. Two things in this pack are indicative
# rather than published, and a local estimator should treat them as such.
#
# 1. The rates. They are market levels for Barcelona in 2026 in EUR, coste
#    directo, and they were authored for the right order of magnitude and the
#    right shape relative to their neighbours. They were NOT extracted from a
#    licensed release of the ITeC BEDEC bank, and they carry no zone
#    coefficient of their own. Before this bill is used for real work every
#    rate should be re-priced from the current bank at the current zone
#    coefficient. The PEM lands near 1,036 EUR per m2 of built area, which is
#    inside the plausible band for this building type but is not a quotation.
#
# 2. The BC3 codes. Only the first two characters of each code, the ITeC
#    chapter, follow the published structure (E2 earthworks and waste, E3
#    foundations and retaining, E4 structure, E5 roofs, E6 walls and
#    partitions, E7 waterproofing and insulation, E8 renders and claddings,
#    E9 floors, EA joinery, EB guarding, ED drainage, EE HVAC, EF pipework,
#    EG electrical, EH lighting, EJ plumbing and hot water, EL lifts, EM fire
#    protection, EN pumps and pressure sets, EP telecoms, EQ fixed equipment,
#    F9 external paving, FR landscaping, H site safety, J testing, K2
#    demolition). The remaining six characters are
#    shaped like a BEDEC reference but are not taken from any published
#    release, so no code below should be assumed to resolve to a specific
#    partida. The one exception is E4B13000 on the column reinforcement line,
#    which is a real BEDEC reference and is what anchors the shape. Stating
#    the boundary this precisely is the point: a wrong code that looks exact
#    is worse than one that is honestly generic, because only the generic one
#    tells the reader to go and look it up.
#
# Two smaller gaps, stated rather than hidden. A real Spanish partida carries
# a precio descompuesto (mano de obra, materiales, maquinaria, medios
# auxiliares, costes indirectos), and BEDEC additionally carries waste and CO2
# figures per partida. The demo template format has no slot for either, so
# every line here is a comprehensive rate only.
#
# The IVA line is the general 21 percent rate. The reduced 10 percent rate
# would also be defensible for this building, and project_metadata["iva_note"]
# sets out exactly when, but that rate depends on how the works are contracted
# rather than on what is being built, so the bill carries the rate that is
# always correct and leaves the reader to switch it knowingly.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="mixed-use-barcelona",
    project_name="Edificio de uso mixto - Barcelona, Poblenou (Mixed-Use Building, Barcelona)",
    project_description=(
        "Edificio de uso mixto de nueva planta en el distrito de Sant Martí (Poblenou), "
        "Barcelona: planta baja comercial y 7 plantas de viviendas sobre rasante, más 2 "
        "plantas de sótano destinadas a aparcamiento y trasteros. 56 viviendas de 1 a 3 "
        "dormitorios, 3 locales comerciales con unos 620 m2 de superficie de venta, 56 plazas "
        "de aparcamiento y 56 trasteros. Superficie construida total aproximada de 8.950 m2, "
        "de los cuales 6.850 m2 sobre rasante y 2.100 m2 bajo rasante, sobre un solar de "
        "1.150 m2. Estructura de hormigón armado con forjado reticular, contención perimetral "
        "mediante muro pantalla, fachada de fábrica con aislamiento térmico por el exterior y "
        "carpintería de aluminio con rotura de puente térmico. Climatización y ACS por "
        "aerotermia con suelo radiante-refrescante, ventilación de doble flujo con recuperación "
        "de calor, edificio de consumo de energía casi nulo según el DB-HE del CTE. Presupuesto "
        "de ejecución material aproximado de 9,27 millones de euros a precios de Barcelona 2026, "
        "unos 1.036 euros por metro cuadrado construido. "
        "New-build mixed-use building in the Sant Marti district (Poblenou) of Barcelona: retail "
        "at ground floor, seven residential storeys above and two basement levels of parking and "
        "storage. 56 flats of one to three bedrooms, three retail units of approx. 620 m2 of "
        "sales floor, 56 parking spaces and 56 storage rooms. Gross built area approx. 8,950 m2 "
        "(6,850 m2 above grade, 2,100 m2 below) on a 1,150 m2 plot. Reinforced concrete frame "
        "with waffle slabs, perimeter diaphragm wall, masonry facade with external insulation "
        "and thermally broken aluminium windows. Air-source heat pumps serve heating, cooling "
        "and domestic hot water through underfloor circuits, with balanced mechanical "
        "ventilation and heat recovery, to the nearly zero energy standard of the CTE. Measured "
        "works approx. EUR 9.27 million at Barcelona 2026 levels, about EUR 1,036 per m2 built."
    ),
    region="ES",
    classification_standard="bc3",
    currency="EUR",
    locale="es",
    address={
        "street": "Carrer de Pallars 312",
        "city": "Barcelona",
        "postcode": "08019",
        "country": "Spain",
        "lat": 41.4030,
        "lng": 2.1985,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    boq_name="Presupuesto de ejecución material por capítulos y partidas (Measured works, PEM)",
    boq_description=(
        "Presupuesto por capítulos y partidas según la práctica española, con precios unitarios "
        "comprensivos referenciados al banco BEDEC del ITeC en el nivel de precios de Barcelona "
        "2026. Sobre el presupuesto de ejecución material se aplican el 13 por ciento de gastos "
        "generales y el 6 por ciento de beneficio industrial para obtener el presupuesto de "
        "ejecución por contrata; el IVA se añade como partida independiente. "
        "Priced by capitulo (chapter) and partida (item) in the Spanish manner, comprehensive "
        "unit rates referenced to the ITeC BEDEC price bank at Barcelona 2026 levels. General "
        "overheads at 13 percent and industrial profit at 6 percent are taken on the measured "
        "works to reach the contract sum, and VAT is shown separately."
    ),
    boq_metadata={
        "standard": "FIEBDC-3 (BC3); banco de precios BEDEC del ITeC (ITeC BEDEC price bank)",
        "phase": "Proyecto ejecutivo - presupuesto de ejecución material (Detailed design, measured works)",
        "base_date": "2026-Q1",
        "price_level": "Barcelona 2026",
        "pricing_method": "Capítulos y partidas con precio unitario comprensivo (chapters and items, all-in rates)",
    },
    sections=[
        # ── 01 Trabajos previos, contención y movimiento de tierras ──────
        (
            "01",
            "Capítulo 1. Trabajos previos, contención y movimiento de tierras (Preliminaries, retaining and earthworks)",
            {"bc3_code": "E2"},
            [
                ("1.1", "Derribo de nave industrial existente de una planta con medios mecánicos, incluida carga (Demolition of existing single-storey warehouse)", "m3", 4_200.0, 12.50, {"bc3_code": "K2151N31"}),
                ("1.2", "Vallado provisional de obra con paneles metálicos de 2 m, montaje y desmontaje (Temporary site hoarding, 2 m panels)", "m", 145.0, 24.00, {"bc3_code": "H6452131"}),
                ("1.3", "Muro pantalla de hormigón armado HA-25 de 45 cm, incluidos muretes guía y viga de coronación (Diaphragm wall HA-25, 450 mm, with guide walls and capping beam)", "m2", 1_250.0, 265.00, {"bc3_code": "E3G53A55"}),
                ("1.4", "Excavación de sótanos a cielo abierto en terreno compacto con medios mecánicos y carga sobre camión (Basement excavation, machine, loaded to lorry)", "m3", 8_400.0, 9.20, {"bc3_code": "E2213422"}),
                ("1.5", "Rebaje del nivel freático mediante pozos de bombeo, instalación y explotación (Groundwater lowering by pumped wells)", "mes", 6.0, 6_200.00, {"bc3_code": "E222B4A1"}),
                ("1.6", "Transporte de tierras y residuos de excavación a gestor autorizado, incluido canon de vertido (Haulage of spoil to licensed facility, tipping fee included)", "m3", 10_900.0, 11.50, {"bc3_code": "E2R642A0"}),
                ("1.7", "Demolición de solera y cimentaciones existentes con martillo hidráulico, incluida carga (Breaking out existing slab and foundations, hydraulic breaker, loaded)", "m3", 285.0, 42.00, {"bc3_code": "K2192913"}),
                ("1.8", "Anclaje provisional al terreno para muro pantalla, perforación, inyección, tesado y retirada (Temporary ground anchor to diaphragm wall, drilled, grouted, stressed and removed)", "u", 34.0, 1_850.00, {"bc3_code": "E3GZ1A0N"}),
            ],
        ),
        # ── 02 Cimentación y estructura ──────────────────────────────────
        (
            "02",
            "Capítulo 2. Cimentación y estructura (Foundations and structure)",
            {"bc3_code": "E4"},
            [
                ("2.1", "Losa de cimentación de hormigón armado HA-30/F/20/IIa+Qb de 80 cm, vertido con bomba, incluido hormigón de limpieza (Raft foundation HA-30, 800 mm, pumped, blinding included)", "m3", 840.0, 148.00, {"bc3_code": "E3C515H4"}),
                ("2.2", "Armadura de losa de cimentación con acero corrugado B500S, elaborada y colocada (Raft reinforcement, B500S, cut, bent and fixed)", "kg", 71_400.0, 1.65, {"bc3_code": "E3CB3000"}),
                ("2.3", "Muros de hormigón armado HA-30 de 30 cm en núcleos y trasdós de pantalla, encofrado a dos caras y armadura (RC walls HA-30, 300 mm, double-sided formwork and rebar)", "m2", 1_620.0, 172.00, {"bc3_code": "E4522DH4"}),
                ("2.4", "Pilares de hormigón armado HA-35/B/20/IIa con encofrado metálico y curado (RC columns HA-35 with steel formwork and curing)", "m3", 386.0, 365.00, {"bc3_code": "E4515DH4"}),
                ("2.5", "Armadura para pilares y muros AP500 S en barras corrugadas B500S (Reinforcement for columns and walls, AP500 S, B500S bars)", "kg", 68_000.0, 1.72, {"bc3_code": "E4B13000"}),
                ("2.6", "Forjado reticular de hormigón armado HA-30 de canto 30+5 cm con casetones recuperables, incluidos encofrado, armadura y hormigonado (Waffle slab HA-30, 30+5 cm, recoverable moulds, all-in)", "m2", 7_900.0, 136.00, {"bc3_code": "E45CA8H4"}),
                ("2.7", "Losa maciza de hormigón armado HA-30 de 25 cm en voladizos, rampas y zonas singulares (Solid RC slab HA-30, 250 mm, to cantilevers, ramps and special areas)", "m2", 1_150.0, 152.00, {"bc3_code": "E45C18H3"}),
                ("2.8", "Escaleras de hormigón armado en losa inclinada de 15 cm, incluidos encofrado y peldañeado (RC stairs, 150 mm inclined slab, formwork and steps included)", "m2", 285.0, 195.00, {"bc3_code": "E45C7AH3"}),
                ("2.9", "Solera de hormigón armado HA-25 de 20 cm sobre encachado de grava, con mallazo, en sótano -2 (Ground-bearing slab HA-25, 200 mm on hardcore, mesh reinforced, level -2)", "m2", 1_050.0, 42.00, {"bc3_code": "E9365G51"}),
                ("2.10", "Pilar metálico de acero S275JR en planta baja para las luces del uso comercial, incluida imprimación (Steel column S275JR at ground floor for the retail spans, primed)", "kg", 18_500.0, 2.85, {"bc3_code": "E4415115"}),
                ("2.11", "Viga de transferencia de hormigón armado HA-40 sobre la planta baja comercial (RC transfer beam HA-40 over the ground-floor retail level)", "m3", 96.0, 425.00, {"bc3_code": "E4535DH5"}),
            ],
        ),
        # ── 03 Cubiertas e impermeabilizaciones ──────────────────────────
        (
            "03",
            "Capítulo 3. Cubiertas e impermeabilizaciones (Roofs and waterproofing)",
            {"bc3_code": "E5"},
            [
                ("3.1", "Formación de pendientes en cubierta con hormigón celular y capa de regularización de mortero (Roof falls in lightweight concrete with mortar levelling coat)", "m2", 900.0, 26.00, {"bc3_code": "E5Z15A2A"}),
                ("3.2", "Cubierta plana invertida transitable con XPS de 80 mm, doble lámina bituminosa y acabado de baldosa (Inverted accessible flat roof, 80 mm XPS, two-ply bituminous membrane, tiled finish)", "m2", 620.0, 148.00, {"bc3_code": "E5122LB3"}),
                ("3.3", "Cubierta plana invertida no transitable con XPS de 100 mm y acabado de grava (Inverted non-accessible flat roof, 100 mm XPS, gravel finish)", "m2", 280.0, 112.00, {"bc3_code": "E5113LB4"}),
                ("3.4", "Impermeabilización del trasdós de muros de sótano con lámina drenante nodular de polietileno y geotextil (Basement wall tanking, nodular drainage sheet and geotextile)", "m2", 1_250.0, 21.00, {"bc3_code": "E7B21A0L"}),
                ("3.5", "Impermeabilización bajo losa de cimentación con lámina de polietileno de alta densidad (Under-raft damp-proof membrane, HDPE sheet)", "m2", 1_150.0, 14.50, {"bc3_code": "E7711A0K"}),
                ("3.6", "Impermeabilización de baños, cocinas y terrazas con membrana líquida de poliuretano (Wet-area waterproofing, liquid polyurethane membrane)", "m2", 1_480.0, 28.00, {"bc3_code": "E7811A01"}),
                ("3.7", "Sumidero sifónico de polipropileno y rebosadero en cubierta, conectado a bajante (Siphonic roof outlet and overflow in polypropylene, connected to stack)", "u", 34.0, 128.00, {"bc3_code": "E5ZH1B61"}),
                ("3.8", "Albardilla de piedra artificial en coronación de petos y remates de cubierta (Precast stone coping to parapets and roof upstands)", "m", 420.0, 58.00, {"bc3_code": "E5ZJ1D6P"}),
                ("3.9", "Cubierta ajardinada extensiva en terraza de planta primera con capa drenante, sustrato y vegetación (Extensive green roof to first-floor terrace, drainage layer, substrate and planting)", "m2", 180.0, 128.00, {"bc3_code": "E5Z2A1B7"}),
            ],
        ),
        # ── 04 Fachadas y cerramientos exteriores ────────────────────────
        (
            "04",
            "Capítulo 4. Fachadas y cerramientos exteriores (Facades and external envelope)",
            {"bc3_code": "E6"},
            [
                ("4.1", "Hoja exterior de fachada de fábrica de ladrillo perforado de 14 cm tomada con mortero, para revestir (External leaf, 140 mm perforated brickwork in mortar, to receive render)", "m2", 2_750.0, 58.00, {"bc3_code": "E612B51K"}),
                ("4.2", "Sistema de aislamiento térmico por el exterior con lana mineral de 100 mm, malla y mortero acrílico (External wall insulation system, 100 mm mineral wool, mesh and acrylic render)", "m2", 2_180.0, 96.00, {"bc3_code": "E7C9B531"}),
                ("4.3", "Aplacado de fachada de planta baja con piedra natural de 3 cm y fijación mecánica oculta (Ground-floor stone cladding, 30 mm, concealed mechanical fixing)", "m2", 420.0, 205.00, {"bc3_code": "E83E23G3"}),
                ("4.4", "Trasdosado interior de fachada con placa de yeso laminado de 15 mm sobre perfilería de 46 mm y lana mineral de 45 mm (Internal lining to facade, 15 mm plasterboard on 46 mm studs, 45 mm mineral wool)", "m2", 2_750.0, 42.00, {"bc3_code": "E6521DBA"}),
                ("4.5", "Barandilla de balcón de vidrio laminado de seguridad 6+6 con perfil de aluminio de fijación continua (Balcony balustrade, 6+6 laminated safety glass in continuous aluminium shoe)", "m", 285.0, 340.00, {"bc3_code": "EB12AB0M"}),
                ("4.6", "Celosía de lamas fijas de aluminio lacado en huecos de patios de instalaciones (Fixed aluminium louvre screen to plant courtyards)", "m2", 96.0, 225.00, {"bc3_code": "EAV8B120"}),
                ("4.7", "Vierteaguas, dinteles y remates de aluminio lacado en huecos de fachada (Aluminium sills, lintel closers and reveal trims to openings)", "m", 640.0, 42.00, {"bc3_code": "E8K1B14K"}),
                ("4.8", "Barandilla de terraza y peto de cubierta de acero galvanizado y lacado, según DB-SUA 1 (Galvanised and powder-coated steel balustrade to terraces and roof parapet, to DB-SUA 1)", "m", 165.0, 195.00, {"bc3_code": "EB14AB2N"}),
            ],
        ),
        # ── 05 Divisorias interiores y aislamientos ──────────────────────
        (
            "05",
            "Capítulo 5. Divisorias interiores y aislamientos (Internal partitions and insulation)",
            {"bc3_code": "E6"},
            [
                ("5.1", "Divisoria entre viviendas de doble hoja de fábrica de 9 cm con lana mineral de 40 mm y trasdosado, según DB-HR (Party wall, twin 90 mm brick leaves, 40 mm mineral wool and lining, to DB-HR)", "m2", 1_850.0, 84.00, {"bc3_code": "E614HSAK"}),
                ("5.2", "Tabiquería interior de vivienda con doble placa de yeso laminado de 13 mm a cada cara sobre perfilería de 48 mm y lana mineral (Internal partitions, twin 13 mm boards each side of 48 mm studs, mineral wool)", "m2", 4_200.0, 48.00, {"bc3_code": "E6524DBA"}),
                ("5.3", "Tabique de placa de yeso laminado hidrófuga en baños y cocinas (Moisture-resistant plasterboard partition to bathrooms and kitchens)", "m2", 1_180.0, 55.00, {"bc3_code": "E6525DHA"}),
                ("5.4", "Aislamiento a ruido de impacto con lámina de polietileno reticulado de 5 mm bajo pavimento (Impact-sound insulation, 5 mm cross-linked polyethylene under floor finish)", "m2", 5_900.0, 8.60, {"bc3_code": "E7C23A51"}),
                ("5.5", "Falso techo registrable de placa de yeso laminado en zonas comunes, baños y pasillos (Demountable plasterboard suspended ceiling to common areas, bathrooms and corridors)", "m2", 2_350.0, 39.00, {"bc3_code": "E8443160"}),
                ("5.6", "Sellado de pasos de instalaciones y compartimentación cortafuegos EI 90, según DB-SI (Fire stopping to service penetrations and EI 90 compartmentation, to DB-SI)", "u", 420.0, 48.00, {"bc3_code": "E7D19V21"}),
                ("5.7", "Trasdosado de placa de yeso laminado en medianeras y núcleo de escaleras con lana mineral (Plasterboard lining to party walls and stair core with mineral wool)", "m2", 1_420.0, 36.00, {"bc3_code": "E6522DBA"}),
            ],
        ),
        # ── 06 Revestimientos y pavimentos ───────────────────────────────
        (
            "06",
            "Capítulo 6. Revestimientos y pavimentos (Renders, tiling and floor finishes)",
            {"bc3_code": "E8"},
            [
                ("6.1", "Enfoscado maestreado de mortero de cemento en sótanos, locales y salas técnicas (Ruled cement-mortar render to basements, retail units and plant rooms)", "m2", 2_850.0, 23.00, {"bc3_code": "E8121112"}),
                ("6.2", "Enlucido de yeso y pintura plástica lisa a dos manos en paramentos verticales y techos (Gypsum skim and two coats of matt emulsion to walls and ceilings)", "m2", 21_500.0, 12.40, {"bc3_code": "E898J2A0"}),
                ("6.3", "Alicatado de baños y cocinas con cerámica de 30x60 cm colocada con adhesivo cementoso (Wall tiling to bathrooms and kitchens, 30x60 cm ceramic on cement adhesive)", "m2", 3_850.0, 52.00, {"bc3_code": "E8251335"}),
                ("6.4", "Recrecido de mortero de cemento de 5 cm como base de pavimento, incluidas instalaciones embebidas (Cement-mortar screed, 50 mm, as floor base, embedded services included)", "m2", 7_050.0, 18.50, {"bc3_code": "E93A14D0"}),
                ("6.5", "Pavimento de tarima laminada AC4 sobre lámina, incluido rodapié, en viviendas (AC4 laminate flooring on underlay with skirting, to dwellings)", "m2", 4_200.0, 58.00, {"bc3_code": "E9QG5A6K"}),
                ("6.6", "Pavimento de gres porcelánico de 60x60 cm en baños, cocinas, terrazas y zonas comunes (Porcelain floor tiling, 60x60 cm, to bathrooms, kitchens, terraces and common areas)", "m2", 2_650.0, 58.00, {"bc3_code": "E9DB1J0K"}),
                ("6.7", "Pavimento continuo de hormigón pulido con endurecedor superficial en aparcamiento y rampas (Power-floated concrete floor with surface hardener to car park and ramps)", "m2", 2_100.0, 33.00, {"bc3_code": "E9G2131K"}),
                ("6.8", "Pavimento de piedra natural en vestíbulo, portal y zaguán de acceso (Natural stone flooring to entrance hall, lobby and access vestibule)", "m2", 190.0, 148.00, {"bc3_code": "E9B11305"}),
            ],
        ),
        # ── 07 Carpintería, vidrio y cerrajería ──────────────────────────
        (
            "07",
            "Capítulo 7. Carpintería, vidrio y cerrajería (Joinery, glazing and metalwork)",
            {"bc3_code": "EA"},
            [
                ("7.1", "Ventana de aluminio lacado con rotura de puente térmico, oscilobatiente, con doble acristalamiento bajo emisivo 6/16/4+4, según DB-HE (Thermally broken aluminium tilt-and-turn window, Low-E DGU 6/16/4+4, to DB-HE)", "m2", 685.0, 485.00, {"bc3_code": "EAF4419C"}),
                ("7.2", "Puerta balconera corredera elevable de aluminio con rotura de puente térmico y vidrio bajo emisivo (Lift-and-slide aluminium balcony door, thermally broken, Low-E glazing)", "m2", 165.0, 545.00, {"bc3_code": "EAF83C6C"}),
                ("7.3", "Persiana enrollable de aluminio inyectado con cajón monoblock aislado y accionamiento motorizado (Injected aluminium roller shutter with insulated monoblock box, motorised)", "m2", 620.0, 112.00, {"bc3_code": "EAV11520"}),
                ("7.4", "Puerta de entrada a vivienda blindada, acabado lacado, con cerradura de seguridad de tres puntos (Reinforced flat entrance door, lacquered, three-point security lock)", "u", 56.0, 845.00, {"bc3_code": "EAQD2465"}),
                ("7.5", "Puerta de paso interior de madera lacada, hoja abatible, incluidos premarco, tapajuntas y herrajes (Internal lacquered timber door, hinged leaf, sub-frame, architraves and ironmongery)", "u", 268.0, 315.00, {"bc3_code": "EAQD1265"}),
                ("7.6", "Puerta cortafuegos EI2 60-C5 en escaleras, trasteros y salas técnicas, con cierrapuertas (EI2 60-C5 fire door to stairs, storage rooms and plant, with closer)", "u", 42.0, 465.00, {"bc3_code": "EASA71PB"}),
                ("7.7", "Escaparate de aluminio y vidrio laminado de seguridad en locales de planta baja (Aluminium shopfront with laminated safety glass to ground-floor retail units)", "m2", 185.0, 495.00, {"bc3_code": "EAF7A1CC"}),
                ("7.8", "Puerta seccional motorizada de acceso al aparcamiento con control de accesos por mando (Motorised sectional car-park door with remote access control)", "u", 1.0, 8_200.00, {"bc3_code": "EARA1D50"}),
                ("7.9", "Barandilla de escalera interior de acero con pasamanos continuo, según DB-SUA 1 (Internal stair balustrade in steel with continuous handrail, to DB-SUA 1)", "m", 165.0, 168.00, {"bc3_code": "EB15A1A1"}),
                ("7.10", "Puerta de acceso al edificio de aluminio y vidrio de seguridad, con cierrapuertas (Building entrance door in aluminium and safety glass, with door closer)", "u", 2.0, 3_850.00, {"bc3_code": "EAF9A2CC"}),
            ],
        ),
        # ── 08 Instalaciones ─────────────────────────────────────────────
        (
            "08",
            "Capítulo 8. Instalaciones (Building services)",
            {"bc3_code": "EE"},
            [
                ("8.1", "Red de saneamiento con bajantes y colectores de PVC insonorizado, arquetas y acometida a la red municipal (Drainage, acoustic PVC stacks and runs, inspection chambers and connection to public sewer)", "m", 1_850.0, 46.00, {"bc3_code": "ED15B871"}),
                ("8.2", "Instalación de fontanería por vivienda con montantes, distribución en polietileno reticulado y contadores centralizados (Plumbing per dwelling, risers, PEX distribution and centralised meters)", "u", 56.0, 2_180.00, {"bc3_code": "EFB14452"}),
                ("8.3", "Aparato sanitario de porcelana vitrificada con grifería monomando y desagüe (Vitreous china sanitary fitting with single-lever tap and waste)", "u", 148.0, 685.00, {"bc3_code": "EJ13B21P"}),
                ("8.4", "Producción centralizada de ACS por aerotermia con acumulación y recirculación, según DB-HE 4 (Centralised heat-pump domestic hot water with storage and recirculation, to DB-HE 4)", "u", 4.0, 34_500.00, {"bc3_code": "EJAB1211"}),
                ("8.5", "Climatización por bomba de calor aire-agua con suelo radiante-refrescante en viviendas (Air-to-water heat-pump heating and cooling with underfloor circuits to dwellings)", "m2", 4_650.0, 118.00, {"bc3_code": "EEH61A5B"}),
                ("8.6", "Ventilación mecánica de doble flujo con recuperador de calor por vivienda, según DB-HS 3 (Balanced mechanical ventilation with heat recovery, one unit per dwelling, to DB-HS 3)", "u", 56.0, 3_150.00, {"bc3_code": "EEM32A6C"}),
                ("8.7", "Ventilación y extracción de humos del aparcamiento con conductos y ventiladores 400 grados C durante 2 h (Car-park ventilation and smoke extract, ductwork and 400 C / 2 h fans)", "m2", 2_100.0, 54.00, {"bc3_code": "EEV21A5D"}),
                ("8.8", "Instalación eléctrica de vivienda con centralización de contadores, derivación individual y cuadro, según REBT (Electrical installation per dwelling, meter bank, submain and consumer unit, to REBT)", "u", 56.0, 3_450.00, {"bc3_code": "EG1B1A2K"}),
                ("8.9", "Instalación eléctrica de servicios comunes, locales y aparcamiento, incluidos cuadros y protecciones (Electrical installation to common services, retail units and car park, boards and protection included)", "pa", 1.0, 138_000.00, {"bc3_code": "EG4243JK"}),
                ("8.10", "Luminaria LED en zonas comunes y aparcamiento con alumbrado de emergencia, según DB-SUA 4 (LED luminaire to common areas and car park with emergency lighting, to DB-SUA 4)", "u", 620.0, 118.00, {"bc3_code": "EH61R3BA"}),
                ("8.11", "Infraestructura común de telecomunicaciones por vivienda con recintos RITI y RITS, canalizaciones y tomas, según RD 346/2011 (Common telecoms infrastructure per dwelling, RITI and RITS rooms, containment and outlets, to RD 346/2011)", "u", 56.0, 845.00, {"bc3_code": "EP7414D3"}),
                ("8.12", "Ascensor eléctrico sin cuarto de máquinas de 630 kg y 10 paradas, accesible según DB-SUA 9 (Machine-room-less electric lift, 630 kg, 10 stops, accessible to DB-SUA 9)", "u", 2.0, 74_500.00, {"bc3_code": "EL22415B"}),
                ("8.13", "Protección contra incendios con detección, bocas de incendio equipadas, extintores y señalización, según DB-SI (Fire protection, detection, hose reels, extinguishers and signage, to DB-SI)", "pa", 1.0, 96_500.00, {"bc3_code": "EM31261J"}),
                ("8.14", "Preinstalación y punto de recarga de vehículo eléctrico en plaza de aparcamiento, según DB-HE 6 e ITC-BT-52 (Electric-vehicle charging point and provision per parking bay, to DB-HE 6 and ITC-BT-52)", "u", 56.0, 465.00, {"bc3_code": "EG4Z1A2K"}),
                ("8.15", "Grupo de presión de agua y depósito de reserva para el abastecimiento de las plantas altas (Booster pump set and break tank for upper-floor water supply)", "u", 1.0, 28_500.00, {"bc3_code": "EN81B2A1"}),
                ("8.16", "Videoportero digital con placa de calle y monitor por vivienda (Digital video entry system, street panel and monitor per dwelling)", "u", 56.0, 465.00, {"bc3_code": "EP2416D5"}),
                ("8.17", "Pararrayos con puesta a tierra general del edificio y red equipotencial (Lightning protection with building earthing and equipotential bonding)", "pa", 1.0, 18_500.00, {"bc3_code": "EGD1222E"}),
            ],
        ),
        # ── 09 Equipamiento, urbanización y gestión de obra ──────────────
        (
            "09",
            "Capítulo 9. Equipamiento, urbanización y gestión de obra (Fit-out, external works and site management)",
            {"bc3_code": "EQ"},
            [
                ("9.1", "Equipamiento de cocina con mobiliario alto y bajo, encimera y fregadero, por vivienda (Kitchen fit-out per dwelling, wall and base units, worktop and sink)", "u", 56.0, 4_650.00, {"bc3_code": "EQ5127B6"}),
                ("9.2", "Urbanización de acera y vado de acceso con pavimento de panot y bordillo de piedra, según ordenanza municipal (Footway and vehicle crossover, panot paving and stone kerb, to municipal ordinance)", "m2", 240.0, 118.00, {"bc3_code": "F9E1310A"}),
                ("9.3", "Estudio de seguridad y salud con protecciones colectivas e individuales durante toda la obra (Health and safety plan, collective and personal protection for the whole works)", "pa", 1.0, 128_000.00, {"bc3_code": "H15Z1001"}),
                ("9.4", "Gestión de residuos de construcción y demolición con clasificación en obra y canon de vertido, según RD 105/2008 (Construction and demolition waste management, on-site sorting and tipping fees, to RD 105/2008)", "pa", 1.0, 68_500.00, {"bc3_code": "E2RA71H0"}),
                ("9.5", "Control de calidad con ensayos de hormigón y acero y pruebas de estanqueidad (Quality control, concrete and steel testing and watertightness tests)", "pa", 1.0, 52_000.00, {"bc3_code": "J060770A"}),
                ("9.6", "Pruebas de servicio, legalización de instalaciones y Libro del Edificio (Commissioning, statutory registration of services and building manual)", "pa", 1.0, 32_000.00, {"bc3_code": "J0B21103"}),
                ("9.7", "Armario empotrado en dormitorios con puertas correderas, balda y barra de colgar (Fitted wardrobe to bedrooms, sliding doors, shelf and hanging rail)", "u", 112.0, 685.00, {"bc3_code": "EQ7128B4"}),
                ("9.8", "Ajardinamiento del patio de manzana con sustrato, plantación y riego por goteo (Courtyard landscaping, substrate, planting and drip irrigation)", "m2", 320.0, 68.00, {"bc3_code": "FR3P2154"}),
            ],
        ),
    ],
    # Spanish price build-up. Gastos generales and beneficio industrial are both
    # taken on the presupuesto de ejecucion material, never one on top of the
    # other, which is why both apply to ``direct_cost``. Their sum gives the
    # presupuesto de ejecucion por contrata, and IVA is the only cumulative
    # line. See project_metadata["iva_note"] for when the reduced 10 percent
    # rate replaces the 21 percent shown here.
    markups=[
        ("Gastos generales 13 por ciento (General overheads, 13 percent of measured works)", 13.0, "overhead", "direct_cost"),
        ("Beneficio industrial 6 por ciento (Industrial profit, 6 percent of measured works)", 6.0, "profit", "direct_cost"),
        ("IVA 21 por ciento (Value added tax at the general rate of 21 percent)", 21.0, "tax", "cumulative"),
    ],
    total_months=24,
    tender_name="Contrata general de obra - Edificio de uso mixto, Poblenou (Main contract)",
    tender_companies=[
        ("Constructora Ribera Nova SA", "licitacions@riberanova.example", 0.97),
        ("Edificacions Aureta SL", "ofertas@aureta.example", 1.02),
        ("Grup Constructor Vallcorb SA", "licitacions@vallcorb.example", 1.01),
    ],
    tender_packages=[
        (
            "Contención, movimiento de tierras y estructura (Retaining, earthworks and structure)",
            "Muro pantalla, excavación de sótanos, losa de cimentación, muros, pilares y forjados reticulares.",
            "evaluating",
            [
                ("Constructora Ribera Nova SA", "licitacions@riberanova.example", 0.97),
                ("Edificacions Aureta SL", "ofertas@aureta.example", 1.02),
                ("Grup Constructor Vallcorb SA", "licitacions@vallcorb.example", 1.01),
            ],
        ),
        (
            "Fachadas, cubiertas y carpintería exterior (Facades, roofs and external joinery)",
            "Fábrica de fachada, aislamiento térmico por el exterior, aplacado de piedra, cubiertas invertidas, carpintería de aluminio y vidrio.",
            "issued",
            [
                ("Façanes i Cobertes Mirvent SL", "ofertas@mirvent.example", 0.99),
                ("Tancaments d'Alumini Talaró SL", "licitacions@talaro.example", 1.04),
                ("Construccions Bergantí SA", "ofertas@berganti.example", 1.02),
            ],
        ),
        (
            "Instalaciones y aparatos elevadores (Building services and lifts)",
            "Saneamiento, fontanería, aerotermia con suelo radiante, ventilación de doble flujo, electricidad, telecomunicaciones, protección contra incendios y ascensores.",
            "issued",
            [
                ("Instal·lacions Termall SL", "ofertas@termall.example", 0.98),
                ("Muntatges Elèctrics Solanera SA", "licitacions@solanera.example", 1.03),
                ("Elevació i Manteniment Puntal SL", "ofertas@puntal.example", 1.01),
            ],
        ),
    ],
    # The generic seed starts the parent programme row at a fixed 2026-04-01 and
    # ends it at start plus total_months, so the activities below run from that
    # same date and span exactly the 24 months declared above. Phases overlap in
    # the usual way, but nothing starts before the programme does.
    schedule_activities=[
        ("Implantación de obra y derribo de la nave existente (Site setup and demolition)", "2026-04-01", "2026-05-31"),
        ("Muro pantalla y excavación de sótanos (Diaphragm wall and basement excavation)", "2026-05-15", "2026-08-31"),
        ("Cimentación y estructura de sótanos (Foundations and basement structure)", "2026-08-01", "2026-11-15"),
        ("Estructura sobre rasante (Superstructure)", "2026-11-01", "2027-04-30"),
        ("Cubiertas e impermeabilizaciones (Roofs and waterproofing)", "2027-04-01", "2027-06-15"),
        ("Cerramiento de fachada y aislamiento exterior (Facade envelope and external insulation)", "2027-03-01", "2027-08-31"),
        ("Carpintería exterior y vidrio (External joinery and glazing)", "2027-06-01", "2027-09-30"),
        ("Albañilería interior y tabiquería (Internal partitions)", "2027-05-01", "2027-09-30"),
        ("Instalaciones, primera fase (Building services, first fix)", "2027-06-01", "2027-11-30"),
        ("Revestimientos y pavimentos (Renders, tiling and floor finishes)", "2027-09-01", "2028-01-15"),
        ("Instalaciones, segunda fase y aparatos elevadores (Second fix and lifts)", "2027-11-01", "2028-02-15"),
        ("Carpintería interior y equipamiento de cocinas (Internal joinery and kitchen fit-out)", "2027-12-01", "2028-02-29"),
        ("Urbanización exterior y acera (External works and footway)", "2028-01-01", "2028-02-29"),
        ("Pruebas de servicio, legalizaciones y fin de obra (Commissioning, legalisation and handover)", "2028-02-01", "2028-03-31"),
    ],
    project_metadata={
        "address": "Carrer de Pallars 312, 08019 Barcelona, España",
        "client": "Promotora Llevant Residencial SL (developer)",
        "architect": "Estudi d'Arquitectura Ponent Vint-i-dos (Ponent 22 architecture studio)",
        "quantity_surveyor": "Oficina Técnica Bastida (arquitecto técnico, dirección de ejecución de la obra)",
        "structural_engineer": "Ingeniería de Estructuras Ferrall SLP",
        "services_engineer": "Ingeniería de Instalaciones Termall SL",
        "gfa_m2": 8950,
        "site_area_m2": 1150,
        "storeys": "Planta baja comercial más 7 plantas de viviendas, 2 sótanos (ground-floor retail plus 7 residential storeys, 2 basements)",
        "basement_levels": 2,
        "dwellings": 56,
        "retail_units": 3,
        "parking_spaces": 56,
        "storage_rooms": 56,
        "construction_standards": [
            "CTE, Código Técnico de la Edificación (RD 314/2006): DB-SE, DB-SI, DB-SUA, DB-HE, DB-HR, DB-HS",
            "Código Estructural (RD 470/2021), que sustituye a la EHE-08 y a la EAE-11",
            "RITE, Reglamento de Instalaciones Térmicas en los Edificios (RD 1027/2007)",
            "REBT, Reglamento Electrotécnico para Baja Tensión (RD 842/2002), con ITC-BT-52 para recarga de vehículo eléctrico",
            "Reglamento ICT de infraestructuras comunes de telecomunicaciones (RD 346/2011)",
            "Decret 141/2012 de condicions mínimes d'habitabilitat dels habitatges (Catalunya)",
            "RD 105/2008 de producción y gestión de residuos de construcción y demolición",
            "LOE, Ley 38/1999 de Ordenación de la Edificación",
        ],
        "estimating_method": (
            "Presupuesto por capítulos y partidas con precios unitarios comprensivos referenciados al banco "
            "BEDEC del ITeC. El presupuesto de ejecución material recoge el coste directo de las partidas; "
            "sobre él se aplican gastos generales y beneficio industrial para llegar al presupuesto de "
            "ejecución por contrata, y el IVA se añade al final. Chapters and items with comprehensive unit "
            "rates from the ITeC BEDEC bank; measured works plus overheads and profit give the contract sum, "
            "with VAT added last."
        ),
        "regulator": (
            "Ajuntament de Barcelona para la licencia de obra mayor y la disciplina urbanística; Agència de "
            "l'Habitatge de Catalunya para la cédula de habitabilidad; Departament d'Empresa i Treball de la "
            "Generalitat para la legalización de instalaciones. Dirección facultativa formada por arquitecto "
            "y arquitecto técnico, con organismo de control técnico para el seguro decenal que exige la LOE."
        ),
        "price_bank": (
            "El banco BEDEC del ITeC, Institut de Tecnologia de la Construcció de Catalunya, es la referencia "
            "de precios habitual en Cataluña. Publica partidas con precio descompuesto, coeficientes de zona "
            "y datos de residuos y emisiones por partida, y se distribuye en el formato abierto de "
            "intercambio FIEBDC-3, cuyos ficheros llevan la extensión BC3. La obra pública catalana suele "
            "pedir el presupuesto en ese formato. The ITeC BEDEC bank is the usual price reference in "
            "Catalonia and is distributed in the open FIEBDC-3 exchange format, whose files carry the BC3 "
            "extension."
        ),
        "iva_note": (
            "El presupuesto lleva el IVA al tipo general del 21 por ciento. Cuando el contrato de ejecución "
            "de obra se formaliza directamente entre promotor y contratista para un edificio destinado "
            "principalmente a viviendas, el artículo 91 de la Ley del IVA permite el tipo reducido del 10 por "
            "ciento sobre la totalidad del contrato; el criterio habitual es que al menos la mitad de la "
            "superficie construida se destine a vivienda, computando el aparcamiento y los trasteros anejos. "
            "Este edificio cumpliría ese criterio, pero el tipo depende de cómo se contrate la obra y no de "
            "lo que se construye, así que el presupuesto se emite al 21 por ciento y el estimador local debe "
            "cambiar la línea si su contrato encaja en el supuesto reducido. The bill carries VAT at the "
            "general 21 percent rate. Where the works contract is formalised directly between developer and "
            "main contractor for a building destined principally to dwellings, article 91 of the Spanish VAT "
            "act allows a reduced 10 percent rate over the whole contract, and a local estimator should "
            "switch the line when that applies."
        ),
        "markup_base_note": (
            "Gastos generales y beneficio industrial se calculan ambos sobre el presupuesto de ejecución "
            "material, no en cascada. El 6 por ciento de beneficio industrial es el valor fijo de la "
            "práctica española y el 13 por ciento de gastos generales es el extremo inferior de la horquilla "
            "del 13 al 17 por ciento que el Reglamento General de la Ley de Contratos de las "
            "Administraciones Públicas fija para la obra pública; en obra privada se toma habitualmente el "
            "13. Overheads and profit both apply to the measured works, not one on top of the other."
        ),
        "energy_performance": (
            "Edificio de consumo de energía casi nulo según el DB-HE en su revisión de 2019, con aerotermia "
            "para calefacción, refrigeración y ACS y ventilación con recuperación de calor. Calificación "
            "energética objetivo A. Nearly zero energy building to the 2019 revision of DB-HE, target energy "
            "rating A."
        ),
        "contract": (
            "Contrato de ejecución de obra a precio cerrado con mediciones contradictorias y revisión por "
            "certificación mensual."
        ),
        "headline_cost_eur": (
            "PEM 9.273.662 EUR; PEC con gastos generales y beneficio industrial 11.035.658 EUR; presupuesto "
            "con IVA al 21 por ciento 13.353.146 EUR."
        ),
    },
    budget_boq_name="Presupuesto de ejecución por contrata - control de costes (Contract sum, cost control)",
    planned_budget=11_035_658.0,
    actual_spend_ratio=0.38,
    spi_override=0.97,
    cpi_override=1.01,
)
