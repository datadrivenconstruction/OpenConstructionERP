# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: portugal-pt - Office Building, Lisbon Parque das Nacoes
# ---------------------------------------------------------------------------
# Portuguese orcamento structured by ProNIC-like chapters. Prices are EUR
# excluding 23% IVA.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-lisbon",
    project_name="Edificio de Escritorios - Lisboa Parque das Nacoes (Office, Lisbon)",
    project_description=(
        "Construcao nova de edificio de escritorios no Parque das Nacoes em "
        "Lisboa, 10 pisos acima do solo e 2 caves com 100 lugares de "
        "estacionamento. Area bruta de construcao cerca de 14 500 m2. "
        "Estrutura de betao armado. NZEB conforme requisitos SCE. New-build "
        "office in Parque das Nacoes, Lisbon, 10 storeys with 2 basements. "
        "GFA approx. 14,500 m2. Priced at Lisbon 2026 levels in EUR "
        "excluding IVA."
    ),
    region="PT",
    classification_standard="masterformat",
    currency="EUR",
    locale="pt",
    address={
        "street": "Rua do Bojador 12",
        "city": "Lisbon",
        "postcode": "1990-024",
        "country": "Portugal",
        "lat": 38.7693,
        "lng": -9.0960,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Orcamento - Edificio Escritorios Parque das Nacoes (Budget)",
    boq_description=(
        "Orcamento detalhado para edificio de escritorios de 10 pisos "
        "com 2 caves. Precos ao nivel de Lisboa 2026 em EUR sem IVA."
    ),
    boq_metadata={
        "standard": "ProNIC + division-based classification",
        "phase": "Orcamento para concurso (Tender budget)",
        "base_date": "2026-Q1",
        "price_level": "Lisboa 2026 (EUR, sem IVA)",
    },
    sections=[
        (
            "01",
            "01 - Estaleiro e trabalhos preparatorios (Preliminaries)",
            {"masterformat": "01 00 00"},
            [
                ("01.01", "Instalacao de estaleiro (Site establishment)", "lsum", 1, 185000.00, {"masterformat": "01 00 00"}),
                ("01.02", "Vedacao e protecao de obra (Site hoarding)", "m", 280, 85.00, {"masterformat": "01 00 00"}),
                ("01.03", "Grua-torre montagem e desmontagem (Tower crane)", "month", 18, 8500.00, {"masterformat": "01 00 00"}),
                ("01.04", "Seguranca e saude no trabalho (Health and safety)", "lsum", 1, 95000.00, {"masterformat": "01 00 00"}),
            ],
        ),
        (
            "02",
            "02 - Movimentacao de terras e fundacoes (Earthworks and foundations)",
            {"masterformat": "31 00 00"},
            [
                ("02.01", "Estudo geotecnico (Geotechnical investigation)", "lsum", 1, 62000.00, {"masterformat": "31 00 00"}),
                ("02.02", "Escavacao geral (Bulk excavation)", "m3", 12000, 12.00, {"masterformat": "31 00 00"}),
                ("02.03", "Transporte a vazadouro (Disposal off site)", "m3", 10000, 18.00, {"masterformat": "31 00 00"}),
                ("02.04", "Contencao periferica estacas prancha (Sheet pile wall)", "m2", 2200, 185.00, {"masterformat": "31 00 00"}),
                ("02.05", "Estacas moldadas 600mm (Bored piles 600mm)", "m", 2800, 135.00, {"masterformat": "31 00 00"}),
                ("02.06", "Macicos de encabeamento C30/37 (Pile caps)", "m3", 850, 265.00, {"masterformat": "03 00 00"}),
                ("02.07", "Laje de fundacao C30/37 (Raft slab)", "m3", 720, 275.00, {"masterformat": "03 00 00"}),
                ("02.08", "Armadura A500NR fundacoes (Reinforcement)", "t", 155, 1350.00, {"masterformat": "03 00 00"}),
                ("02.09", "Impermeabilizacao cave (Basement waterproofing)", "m2", 2400, 45.00, {"masterformat": "07 00 00"}),
            ],
        ),
        (
            "03",
            "03 - Estrutura (Structure)",
            {"masterformat": "03 00 00"},
            [
                ("03.01", "Pilares betao armado C40/50 (RC columns)", "m3", 480, 385.00, {"masterformat": "03 00 00"}),
                ("03.02", "Paredes nucleo C40/50 (RC core walls)", "m3", 1050, 365.00, {"masterformat": "03 00 00"}),
                ("03.03", "Laje fungiforme C35/45, 260mm (Flat slab)", "m2", 13000, 115.00, {"masterformat": "03 00 00"}),
                ("03.04", "Armadura superstrutura A500NR (Reinforcement)", "t", 1350, 1380.00, {"masterformat": "03 00 00"}),
                ("03.05", "Cofragem (Formwork)", "m2", 26000, 35.00, {"masterformat": "03 00 00"}),
                ("03.06", "Escadas pre-fabricadas (Precast stairs)", "pcs", 20, 5800.00, {"masterformat": "03 00 00"}),
            ],
        ),
        (
            "04",
            "04 - Paredes exteriores e revestimentos (External walls)",
            {"masterformat": "04 00 00"},
            [
                ("04.01", "Fachada cortina vidro triplo (Curtain wall triple glazed)", "m2", 5400, 620.00, {"masterformat": "08 00 00"}),
                ("04.02", "Revestimento pedra natural embasamento (Stone cladding podium)", "m2", 650, 265.00, {"masterformat": "07 00 00"}),
                ("04.03", "Portas entrada aluminio automaticas (Entrance doors automatic)", "pcs", 4, 8200.00, {"masterformat": "08 00 00"}),
                ("04.04", "Protecao solar exterior brises (External sun shading)", "m2", 2800, 148.00, {"masterformat": "10 00 00"}),
                ("04.05", "Caixilharia aluminio abertura (Opening windows)", "pcs", 240, 1280.00, {"masterformat": "08 00 00"}),
            ],
        ),
        (
            "05",
            "05 - Paredes interiores e acabamentos (Internal walls and finishes)",
            {"masterformat": "09 00 00"},
            [
                ("05.01", "Divisorias gesso cartonado dupla face 100mm (Drywall partition)", "m2", 6800, 52.00, {"masterformat": "09 00 00"}),
                ("05.02", "Divisorias corta-fogo EI60/120 (Fire rated partition)", "m2", 1800, 128.00, {"masterformat": "09 00 00"}),
                ("05.03", "Divisorias vidro escritorios (Glazed office partition)", "m2", 2600, 295.00, {"masterformat": "08 00 00"}),
                ("05.04", "Portas interiores madeira (Internal timber doors)", "pcs", 180, 680.00, {"masterformat": "08 00 00"}),
                ("05.05", "Portas corta-fogo EI30/60 (Fire doors)", "pcs", 64, 1150.00, {"masterformat": "08 00 00"}),
                ("05.06", "Revestimento ceramico IS (Wall tiles WCs)", "m2", 1200, 62.00, {"masterformat": "09 00 00"}),
                ("05.07", "Pintura latex 2 demaos (Emulsion paint 2 coats)", "m2", 16000, 7.50, {"masterformat": "09 00 00"}),
                ("05.08", "Pavimento elevado 150mm (Raised access floor)", "m2", 10500, 75.00, {"masterformat": "09 00 00"}),
                ("05.09", "Carpete em placa escritorios (Carpet tile offices)", "m2", 8800, 42.00, {"masterformat": "09 00 00"}),
                ("05.10", "Pavimento ceramico lobby (Porcelain tile lobby)", "m2", 1100, 118.00, {"masterformat": "09 00 00"}),
                ("05.11", "Teto falso metalico (Suspended metal ceiling)", "m2", 10500, 58.00, {"masterformat": "09 00 00"}),
            ],
        ),
        (
            "06",
            "06 - Cobertura (Roof)",
            {"masterformat": "07 00 00"},
            [
                ("06.01", "Isolamento termico PIR 180mm (Roof insulation)", "m2", 1400, 55.00, {"masterformat": "07 00 00"}),
                ("06.02", "Impermeabilizacao membrana TPO (Roof membrane)", "m2", 1400, 42.00, {"masterformat": "07 00 00"}),
                ("06.03", "Cobertura verde extensiva (Extensive green roof)", "m2", 500, 68.00, {"masterformat": "07 00 00"}),
                ("06.04", "Drenagem cobertura (Roof drainage)", "lsum", 1, 35000.00, {"masterformat": "07 00 00"}),
                ("06.05", "Paineis fotovoltaicos 50 kWp (PV array)", "lsum", 1, 85000.00, {"masterformat": "48 00 00"}),
            ],
        ),
        (
            "07",
            "07 - Instalacoes mecanicas (Mechanical services)",
            {"masterformat": "23 00 00"},
            [
                ("07.01", "Bomba de calor ar-agua 160 kW (Air source heat pump)", "lsum", 1, 135000.00, {"masterformat": "23 00 00"}),
                ("07.02", "UTAN com recuperacao calor (AHU with heat recovery)", "pcs", 4, 58000.00, {"masterformat": "23 00 00"}),
                ("07.03", "Rede de condutas (Ductwork)", "m2", 4200, 62.00, {"masterformat": "23 00 00"}),
                ("07.04", "Rede de aguas e esgotos (Plumbing and drainage)", "lsum", 1, 285000.00, {"masterformat": "22 00 00"}),
                ("07.05", "Loucas sanitarias completas (Sanitaryware)", "pcs", 105, 820.00, {"masterformat": "22 00 00"}),
            ],
        ),
        (
            "08",
            "08 - Instalacoes electricas (Electrical services)",
            {"masterformat": "26 00 00"},
            [
                ("08.01", "Quadro geral BT (Main LV switchboard)", "pcs", 1, 58000.00, {"masterformat": "26 00 00"}),
                ("08.02", "Quadros de piso (Floor distribution boards)", "pcs", 12, 4500.00, {"masterformat": "26 00 00"}),
                ("08.03", "Grupo gerador 400 kVA (Standby generator)", "pcs", 1, 135000.00, {"masterformat": "26 00 00"}),
                ("08.04", "Iluminacao LED DALI (LED lighting)", "m2", 13000, 48.00, {"masterformat": "26 00 00"}),
                ("08.05", "SADI sistema de detecao de incendio (Fire detection)", "m2", 14500, 13.00, {"masterformat": "21 00 00"}),
                ("08.06", "Rede de sprinklers (Sprinkler system)", "m2", 14500, 30.00, {"masterformat": "21 00 00"}),
                ("08.07", "Elevadores 1600 kg, 12 paradas (Passenger lifts)", "pcs", 3, 148000.00, {"masterformat": "14 00 00"}),
                ("08.08", "Elevador monta-cargas 2000 kg (Goods lift)", "pcs", 1, 168000.00, {"masterformat": "14 00 00"}),
                ("08.09", "Cablagem estruturada Cat 6A (Structured cabling)", "m2", 10500, 24.00, {"masterformat": "27 00 00"}),
                ("08.10", "GTC sistema gestao tecnica (BMS)", "lsum", 1, 185000.00, {"masterformat": "27 00 00"}),
                ("08.11", "Controlo de acessos e CCTV (Access control and CCTV)", "lsum", 1, 125000.00, {"masterformat": "27 00 00"}),
                ("08.12", "Sistema anti-intrusao (Intruder alarm)", "lsum", 1, 42000.00, {"masterformat": "27 00 00"}),
                ("08.13", "Postos carregamento EV 11 kW (EV charging)", "pcs", 10, 2200.00, {"masterformat": "26 00 00"}),
                ("08.14", "Comissionamento e ensaios (Commissioning)", "lsum", 1, 85000.00, {"masterformat": "01 00 00"}),
                ("08.15", "Aproveitamento aguas pluviais (Rainwater harvesting)", "lsum", 1, 38000.00, {"masterformat": "22 00 00"}),
                ("08.16", "Iluminacao de emergencia (Emergency lighting)", "lsum", 1, 52000.00, {"masterformat": "26 00 00"}),
                ("08.17", "UPS para sala de servidores (UPS for server room)", "pcs", 1, 48000.00, {"masterformat": "26 00 00"}),
            ],
        ),
        (
            "09",
            "09 - Arranjos exteriores (External works)",
            {"masterformat": "32 00 00"},
            [
                ("09.01", "Pavimentos exteriores (Hard landscaping)", "m2", 1500, 88.00, {"masterformat": "32 00 00"}),
                ("09.02", "Espacos verdes (Soft landscaping)", "m2", 1100, 48.00, {"masterformat": "32 00 00"}),
                ("09.03", "Rede exterior de drenagem (External drainage)", "lsum", 1, 115000.00, {"masterformat": "22 00 00"}),
                ("09.04", "Iluminacao exterior (External lighting)", "pcs", 22, 2100.00, {"masterformat": "26 00 00"}),
                ("09.05", "Estacionamento bicicletas 50 lugares (Bicycle parking)", "pcs", 50, 260.00, {"masterformat": "32 00 00"}),
            ],
        ),
    ],
    markups=[
        ("Encargos de estaleiro (Site overheads)", 10.0, "overhead", "direct_cost"),
        ("Encargos gerais (Head office overheads)", 6.0, "overhead", "direct_cost"),
        ("Lucro (Profit)", 5.0, "profit", "direct_cost"),
        ("IVA 23%", 23.0, "tax", "cumulative"),
    ],
    total_months=26,
    tender_name="Empreitada Geral - Edificio Escritorios Parque das Nacoes",
    tender_companies=[
        ("Almeida Construcoes SA", "concurso@almeida-const.example", 0.98),
        ("Ribeiro e Filhos Lda", "propostas@ribeiro-filhos.example", 1.03),
        ("Teixeira Engenharia SA", "concurso@teixeira-eng.example", 1.01),
    ],
    project_metadata={
        "address": "Rua do Bojador 12, 1990-024 Lisboa",
        "client": "Tejo Investments SA",
        "architect": "Ateliery Santos Arquitectura Lda",
        "structural_engineer": "Fernandes Engenharia SA",
        "qs": "Oliveira Medicoes Lda",
        "gfa_m2": 14500,
        "storeys_above": 10,
        "storeys_below": 2,
        "parking_spaces": 100,
        "energy_class": "NZEB (SCE)",
    },
    tender_packages=[
        (
            "Estrutura (Structure)",
            "Fundacoes, estrutura betao armado",
            "evaluating",
            [
                ("Almeida Construcoes SA", "concurso@almeida-const.example", 0.98),
                ("Ribeiro e Filhos Lda", "propostas@ribeiro-filhos.example", 1.03),
                ("Teixeira Engenharia SA", "concurso@teixeira-eng.example", 1.01),
            ],
        ),
        (
            "Instalacoes (M&E Services)",
            "AVAC, electricidade, seguranca contra incendio, elevadores",
            "issued",
            [
                ("Lopes Instalacoes Lda", "concurso@lopes-inst.example", 0.99),
                ("Sousa Sistemas SA", "propostas@sousa-sist.example", 1.04),
            ],
        ),
    ],
)
