# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: portugal-pt - Residential, Porto Boavista
# ---------------------------------------------------------------------------
# Portuguese residential orcamento. Prices are EUR excluding 23% IVA.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-porto",
    project_name="Edificio Residencial - Porto Boavista (Residential, Porto)",
    project_description=(
        "Construcao nova de edificio residencial na zona da Boavista no "
        "Porto, 8 pisos com 84 fracoes, espacos comerciais no res-do-chao "
        "e estacionamento subterraneo com 95 lugares. Area bruta cerca de "
        "11 000 m2. Estrutura de betao armado. Classe energetica A. "
        "New-build residential in Porto Boavista, 8 storeys, 84 flats, "
        "ground-floor retail, underground car park. GFA approx. 11,000 m2. "
        "Priced at Porto 2026 levels in EUR excluding IVA."
    ),
    region="PT",
    classification_standard="masterformat",
    currency="EUR",
    locale="pt",
    address={
        "street": "Avenida da Boavista 1200",
        "city": "Porto",
        "postcode": "4100-130",
        "country": "Portugal",
        "lat": 41.1587,
        "lng": -8.6457,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Orcamento - Edificio Residencial Boavista (Budget)",
    boq_description=(
        "Orcamento detalhado para edificio residencial de 84 fracoes. "
        "Precos Porto 2026 em EUR sem IVA."
    ),
    boq_metadata={
        "standard": "ProNIC + division-based classification",
        "phase": "Orcamento para concurso (Tender budget)",
        "base_date": "2026-Q1",
        "price_level": "Porto 2026 (EUR, sem IVA)",
    },
    sections=[
        (
            "01",
            "01 - Estaleiro (Preliminaries)",
            {"masterformat": "01 00 00"},
            [
                ("01.01", "Instalacao de estaleiro (Site establishment)", "lsum", 1, 125000.00, {"masterformat": "01 00 00"}),
                ("01.02", "Vedacao de obra (Site hoarding)", "m", 220, 72.00, {"masterformat": "01 00 00"}),
                ("01.03", "Grua-torre (Tower crane)", "month", 14, 6500.00, {"masterformat": "01 00 00"}),
            ],
        ),
        (
            "02",
            "02 - Movimentacao de terras e fundacoes (Earthworks and foundations)",
            {"masterformat": "31 00 00"},
            [
                ("02.01", "Escavacao geral (Bulk excavation)", "m3", 8500, 11.00, {"masterformat": "31 00 00"}),
                ("02.02", "Transporte a vazadouro (Disposal off site)", "m3", 7200, 16.00, {"masterformat": "31 00 00"}),
                ("02.03", "Contencao periferica (Shoring)", "m2", 1600, 165.00, {"masterformat": "31 00 00"}),
                ("02.04", "Estacas moldadas 450mm (Bored piles 450mm)", "m", 2200, 118.00, {"masterformat": "31 00 00"}),
                ("02.05", "Macicos e vigas de fundacao C30/37 (Pile caps and beams)", "m3", 650, 255.00, {"masterformat": "03 00 00"}),
                ("02.06", "Laje de fundacao C30/37 (Ground slab)", "m3", 520, 265.00, {"masterformat": "03 00 00"}),
                ("02.07", "Armadura fundacoes A500NR (Reinforcement)", "t", 115, 1320.00, {"masterformat": "03 00 00"}),
                ("02.08", "Impermeabilizacao cave (Basement waterproofing)", "m2", 1800, 42.00, {"masterformat": "07 00 00"}),
            ],
        ),
        (
            "03",
            "03 - Estrutura (Structure)",
            {"masterformat": "03 00 00"},
            [
                ("03.01", "Pilares C35/45 (RC columns)", "m3", 280, 365.00, {"masterformat": "03 00 00"}),
                ("03.02", "Paredes resistentes C35/45 (RC shear walls)", "m3", 850, 345.00, {"masterformat": "03 00 00"}),
                ("03.03", "Laje fungiforme C30/37, 220mm (Flat slab)", "m2", 10000, 105.00, {"masterformat": "03 00 00"}),
                ("03.04", "Armadura superestrutura A500NR (Reinforcement)", "t", 1050, 1350.00, {"masterformat": "03 00 00"}),
                ("03.05", "Cofragem (Formwork)", "m2", 20000, 32.00, {"masterformat": "03 00 00"}),
                ("03.06", "Escadas pre-fabricadas (Precast stairs)", "pcs", 16, 5200.00, {"masterformat": "03 00 00"}),
            ],
        ),
        (
            "04",
            "04 - Paredes exteriores (External walls)",
            {"masterformat": "04 00 00"},
            [
                ("04.01", "Alvenaria com isolamento ETICS (Cavity wall with ETICS)", "m2", 4800, 165.00, {"masterformat": "07 00 00"}),
                ("04.02", "Reboco exterior (External render)", "m2", 3200, 58.00, {"masterformat": "09 00 00"}),
                ("04.03", "Caixilharia aluminio vidro triplo (Windows triple glazed)", "m2", 1800, 345.00, {"masterformat": "08 00 00"}),
                ("04.04", "Portas corredicas varandas (Sliding balcony doors)", "pcs", 84, 1280.00, {"masterformat": "08 00 00"}),
                ("04.05", "Guardas de varandas vidro e aco (Balcony balustrade)", "m", 840, 235.00, {"masterformat": "05 00 00"}),
                ("04.06", "Montras aluminio (Shopfront glazing)", "m2", 280, 385.00, {"masterformat": "08 00 00"}),
                ("04.07", "Portas de entrada e pala (Entrance doors and canopy)", "pcs", 3, 7200.00, {"masterformat": "08 00 00"}),
                ("04.08", "Impermeabilizacao varandas (Balcony waterproofing)", "m2", 1260, 38.00, {"masterformat": "07 00 00"}),
                ("04.09", "Selante juntas exteriores (External sealant joints)", "m", 2800, 12.00, {"masterformat": "07 00 00"}),
                ("04.10", "Grelhas ventilacao areas tecnicas (Service louvres)", "m2", 380, 118.00, {"masterformat": "08 00 00"}),
                ("04.11", "Escada emergencia metalica (External fire escape stair)", "pcs", 2, 15000.00, {"masterformat": "05 00 00"}),
                ("04.12", "Revestimento pedra embasamento (Stone plinth cladding)", "m2", 280, 78.00, {"masterformat": "07 00 00"}),
            ],
        ),
        (
            "05",
            "05 - Paredes interiores e acabamentos (Internal walls and finishes)",
            {"masterformat": "09 00 00"},
            [
                ("05.01", "Divisorias tijolo 110mm (Block partition 110mm)", "m2", 7800, 35.00, {"masterformat": "09 00 00"}),
                ("05.02", "Divisorias tijolo 70mm (Block partition 70mm)", "m2", 5200, 28.00, {"masterformat": "09 00 00"}),
                ("05.03", "Reboco interior (Internal plaster)", "m2", 28000, 10.00, {"masterformat": "09 00 00"}),
                ("05.04", "Pintura tinta plastica (Emulsion paint)", "m2", 42000, 6.50, {"masterformat": "09 00 00"}),
                ("05.05", "Revestimento ceramico IS (Bathroom wall tiles)", "m2", 3400, 55.00, {"masterformat": "09 00 00"}),
                ("05.06", "Pavimento flutuante laminado (Laminate flooring)", "m2", 5400, 42.00, {"masterformat": "09 00 00"}),
                ("05.07", "Pavimento ceramico cozinhas e halls (Ceramic floor tile)", "m2", 3200, 42.00, {"masterformat": "09 00 00"}),
                ("05.08", "Portas interiores madeira (Internal timber doors)", "pcs", 336, 465.00, {"masterformat": "08 00 00"}),
                ("05.09", "Portas corta-fogo EI30 (Fire doors)", "pcs", 88, 785.00, {"masterformat": "08 00 00"}),
                ("05.10", "Cozinha base por fracao (Kitchen units per flat)", "unit", 84, 3500.00, {"masterformat": "12 00 00"}),
                ("05.11", "Roupeiro embutido por fracao (Built-in wardrobe per flat)", "unit", 84, 1150.00, {"masterformat": "12 00 00"}),
                ("05.12", "Loucas sanitarias por fracao (Sanitaryware per flat)", "unit", 84, 2400.00, {"masterformat": "22 00 00"}),
                ("05.13", "Rodape madeira lacado (Painted timber skirting)", "m", 5600, 10.00, {"masterformat": "09 00 00"}),
                ("05.14", "Corrimao e guarda escadas (Stair handrail and balustrade)", "m", 320, 195.00, {"masterformat": "05 00 00"}),
                ("05.15", "Caixas de correio e sinalizacao (Letterboxes and signage)", "pcs", 2, 3800.00, {"masterformat": "10 00 00"}),
                ("05.16", "Teto falso gesso cartonado (Plasterboard ceiling)", "m2", 6800, 22.00, {"masterformat": "09 00 00"}),
            ],
        ),
        (
            "06",
            "06 - Cobertura (Roof)",
            {"masterformat": "07 00 00"},
            [
                ("06.01", "Isolamento PIR 200mm (Roof insulation)", "m2", 1400, 52.00, {"masterformat": "07 00 00"}),
                ("06.02", "Impermeabilizacao membrana PVC (Roof membrane)", "m2", 1400, 38.00, {"masterformat": "07 00 00"}),
                ("06.03", "Drenagem cobertura (Roof drainage)", "lsum", 1, 28000.00, {"masterformat": "07 00 00"}),
                ("06.04", "Paineis FV 35 kWp (PV array)", "lsum", 1, 62000.00, {"masterformat": "48 00 00"}),
            ],
        ),
        (
            "07",
            "07 - Instalacoes (Services)",
            {"masterformat": "23 00 00"},
            [
                ("07.01", "Bomba de calor colectiva 90 kW (Communal heat pump)", "lsum", 1, 105000.00, {"masterformat": "23 00 00"}),
                ("07.02", "Piso radiante por fracao (Underfloor heating per flat)", "unit", 84, 2800.00, {"masterformat": "23 00 00"}),
                ("07.03", "VMC com recuperacao calor (MVHR per flat)", "unit", 84, 2200.00, {"masterformat": "23 00 00"}),
                ("07.04", "Instalacao electrica por fracao (Electrical per flat)", "unit", 84, 4200.00, {"masterformat": "26 00 00"}),
                ("07.05", "Electricidade partes comuns (Common electrical)", "lsum", 1, 165000.00, {"masterformat": "26 00 00"}),
                ("07.06", "Canalizacao por fracao (Plumbing per flat)", "unit", 84, 5200.00, {"masterformat": "22 00 00"}),
                ("07.07", "SADI sistema de detecao (Fire detection)", "m2", 11000, 12.00, {"masterformat": "21 00 00"}),
                ("07.08", "Elevadores 8 pessoas, 9 paradas (Passenger lifts)", "pcs", 2, 115000.00, {"masterformat": "14 00 00"}),
                ("07.09", "Para-raios (Lightning protection)", "lsum", 1, 32000.00, {"masterformat": "26 00 00"}),
                ("07.10", "Videoporteiro por fracao (Video intercom per flat)", "unit", 84, 380.00, {"masterformat": "27 00 00"}),
                ("07.11", "CCTV areas comuns (CCTV common areas)", "lsum", 1, 48000.00, {"masterformat": "27 00 00"}),
                ("07.12", "Controlo de acessos (Access control)", "pcs", 6, 3500.00, {"masterformat": "27 00 00"}),
                ("07.13", "Postos carregamento EV (EV charging points)", "pcs", 10, 2200.00, {"masterformat": "26 00 00"}),
                ("07.14", "Solar termico colectivo (Solar thermal collective)", "lsum", 1, 72000.00, {"masterformat": "23 00 00"}),
                ("07.15", "Sprinklers (Sprinkler system)", "m2", 11000, 28.00, {"masterformat": "21 00 00"}),
                ("07.16", "Retencao aguas pluviais (Rainwater retention)", "lsum", 1, 38000.00, {"masterformat": "22 00 00"}),
            ],
        ),
        (
            "08",
            "08 - Arranjos exteriores (External works)",
            {"masterformat": "32 00 00"},
            [
                ("08.01", "Pavimentos exteriores (Hard landscaping)", "m2", 1600, 78.00, {"masterformat": "32 00 00"}),
                ("08.02", "Espacos verdes (Soft landscaping)", "m2", 1200, 42.00, {"masterformat": "32 00 00"}),
                ("08.03", "Rede de drenagem (External drainage)", "lsum", 1, 85000.00, {"masterformat": "22 00 00"}),
                ("08.04", "Iluminacao exterior (External lighting)", "pcs", 18, 1850.00, {"masterformat": "26 00 00"}),
                ("08.05", "Parque bicicletas 84 lugares (Bicycle parking)", "pcs", 84, 235.00, {"masterformat": "32 00 00"}),
                ("08.06", "Vedacao e portao (Boundary fence and gate)", "m", 180, 125.00, {"masterformat": "32 00 00"}),
                ("08.07", "Parque infantil (Playground)", "lsum", 1, 35000.00, {"masterformat": "32 00 00"}),
                ("08.08", "Ponto de recolha de residuos (Refuse collection point)", "pcs", 2, 6500.00, {"masterformat": "32 00 00"}),
            ],
        ),
    ],
    markups=[
        ("Encargos de estaleiro (Site overheads)", 9.0, "overhead", "direct_cost"),
        ("Encargos gerais (Head office overheads)", 5.0, "overhead", "direct_cost"),
        ("Lucro (Profit)", 5.0, "profit", "direct_cost"),
        ("IVA 23%", 23.0, "tax", "cumulative"),
    ],
    total_months=22,
    tender_name="Empreitada - Edificio Residencial Boavista",
    tender_companies=[
        ("Pereira Construcoes Lda", "concurso@pereira-const.example", 0.99),
        ("Costa e Silva Empreitadas SA", "propostas@costasilva.example", 1.02),
        ("Moreira Engenharia Lda", "concurso@moreira-eng.example", 1.04),
    ],
    project_metadata={
        "address": "Avenida da Boavista 1200, 4100-130 Porto",
        "client": "Douro Real Estate Lda",
        "architect": "Carvalho Arquitectos Lda",
        "structural_engineer": "Martins Engenharia SA",
        "qs": "Barros Medicoes Lda",
        "gfa_m2": 11000,
        "units": 84,
        "storeys_above": 8,
        "storeys_below": 1,
        "parking_spaces": 95,
        "energy_class": "A",
    },
)
