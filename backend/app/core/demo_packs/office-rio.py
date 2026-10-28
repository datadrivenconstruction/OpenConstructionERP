# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Flagship demo: Edificio Comercial Corporativo - Rio de Janeiro (BR)
# ---------------------------------------------------------------------------
# Orcamento sintetico no padrao brasileiro (SINAPI / NBR) para uma torre
# comercial corporativa (lajes de escritorio) em concreto armado na regiao do
# Porto Maravilha, Centro do Rio de Janeiro. Precos a nivel Rio de Janeiro
# 2026 (referencia SINAPI Desonerado RJ), moeda BRL, locale pt-BR.
# Distinto do demo residencial de Sao Paulo: aqui e uma torre comercial AAA
# com fachada cortina (pele de vidro), AVAC central, lajes de grande vao e
# certificacao LEED. Composicoes citam codigos SINAPI representativos e normas
# NBR aplicaveis. classification_standard "masterformat" e usado apenas como
# fallback de plataforma; cada item carrega codigo SINAPI e/ou NBR no
# dicionario de classificacao.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-rio",
    project_name="Edifício Comercial Corporativo - Rio de Janeiro (Porto Maravilha)",
    project_description=(
        "Construção de torre comercial corporativa (edifício de escritórios "
        "classe AAA) em concreto armado, 22 pavimentos-tipo de lajes "
        "corporativas + térreo (lobby de pe-direito duplo) + 4 subsolos de "
        "garagem. Área de terreno ~3.400 m2, área construída total (ABC) "
        "~46.500 m2, lajes de escritório de ~1.450 m2 por pavimento com vao "
        "livre de 12 m. Estrutura em concreto armado moldado in loco (NBR "
        "6118) com núcleo rígido de circulação e lajes protendidas. Fachada "
        "cortina unitizada (pele de vidro) com vidro insulado de controle "
        "solar e brises. Sistema central de climatização (AVAC) com chiller e "
        "fan-coils, 6 elevadores de alta velocidade com despacho inteligente. "
        "Acessibilidade NBR 9050, desempenho NBR 15575, SPDA NBR 5419, projeto "
        "e proteção contra incêndio aprovados pelo Corpo de Bombeiros do Estado "
        "do Rio de Janeiro (CBMERJ), certificação LEED Core & Shell (nível "
        "ouro pretendido). Custo de obra (custo direto) ~R$ 285 milhões."
    ),
    region="BR",
    classification_standard="masterformat",
    currency="BRL",
    locale="pt-BR",
    address={
        "street": "Avenida Rodrigues Alves 250",
        "city": "Rio de Janeiro",
        "postcode": "20220-360",
        "country": "Brazil",
        "lat": -22.8966,
        "lng": -43.1862,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    boq_name="Orçamento Sintético Corporativo - Padrão SINAPI",
    boq_description=(
        "Orçamento sintético por etapas conforme prática brasileira para "
        "edifício comercial corporativo, composições referenciadas ao SINAPI "
        "(CAIXA/IBGE) Rio de Janeiro, desonerado. BDI aplicado sobre o custo "
        "direto."
    ),
    boq_metadata={
        "standard": "SINAPI / NBR (orçamento sintético)",
        "phase": "Projeto executivo - orçamento de obra",
        "base_date": "2026-01",
        "price_level": "Rio de Janeiro (RJ) 2026 - SINAPI Desonerado",
    },
    sections=[
        # ── 01 Servicos preliminares e canteiro (Preliminaries / site) ───
        (
            "01",
            "Serviços Preliminares e Canteiro (Preliminaries / site setup)",
            {"sinapi": "SERV. PRELIMINARES"},
            [
                ("01.001", "Placa de obra em chapa galvanizada 6,0x3,0m (Site signboard)", "m2", 18, 395.00, {"sinapi": "74209/001"}),
                ("01.002", "Tapume metálico galvanizado h=2,40m no perímetro (Site hoarding)", "m2", 980, 118.00, {"sinapi": "73604"}),
                ("01.003", "Canteiro de obra em containers metálicos modulares (Modular site offices)", "m2", 640, 680.00, {"sinapi": "73847/001"}),
                ("01.004", "Ligação provisória de água e esgoto (Temporary water/sewer)", "vb", 1, 28000.00, {"sinapi": "98459"}),
                ("01.005", "Ligação provisória de energia elétrica em média tensão (Temporary MV power)", "vb", 1, 68000.00, {"sinapi": "98460"}),
                ("01.006", "Locação da obra georreferenciada com estação total (Setting out survey)", "m2", 3400, 16.50, {"sinapi": "74077/001"}),
                ("01.007", "Mobilização e desmobilização de equipamentos (Mob/demob)", "vb", 1, 185000.00, {"sinapi": "ADMIN"}),
                ("01.008", "Limpeza permanente da obra (Continuous site cleaning)", "mes", 32, 12500.00, {"sinapi": "97644"}),
                ("01.009", "Equipamento de proteção coletiva conforme NR-18 (Collective safety/NR-18)", "vb", 1, 320000.00, {"nbr": "NR-18"}),
                ("01.010", "Grua fixa torre de grande capacidade - locação mensal (Tower crane rental)", "mes", 26, 64000.00, {"sinapi": "EQUIP"}),
                ("01.011", "Plano de gerenciamento de resíduos da construção civil PGRCC (Waste mgmt plan)", "vb", 1, 95000.00, {"nbr": "NBR 15112"}),
            ],
        ),
        # ── 02 Movimento de terra e contencao (Earthworks / shoring) ─────
        (
            "02",
            "Movimento de Terra e Contenção (Earthworks and shoring)",
            {"sinapi": "MOV. TERRA"},
            [
                ("02.001", "Escavação mecanizada dos 4 subsolos (Mechanical excavation)", "m3", 58000, 22.50, {"sinapi": "90082"}),
                ("02.002", "Carga, transporte e bota-fora até 15km DMT (Haul/disposal)", "m3", 62000, 38.00, {"sinapi": "93590"}),
                ("02.003", "Parede diafragma em concreto armado e=60cm (Diaphragm wall)", "m2", 6200, 685.00, {"nbr": "NBR 6122"}),
                ("02.004", "Tirantes ancorados protendidos permanentes (Permanent ground anchors)", "m", 3800, 195.00, {"nbr": "NBR 5629"}),
                ("02.005", "Rebaixamento de lençol freático por ponteiras (Wellpoint dewatering)", "vb", 1, 480000.00, {"sinapi": "DRENAGEM"}),
                ("02.006", "Reaterro apiloado em camadas com compactação (Compacted backfill)", "m3", 8400, 32.00, {"sinapi": "93382"}),
                ("02.007", "Lastro de brita apiloado e=15cm (Crushed-stone bed)", "m2", 3300, 26.50, {"sinapi": "96617"}),
                ("02.008", "Instrumentação geotécnica e monitoramento (Geotechnical monitoring)", "vb", 1, 165000.00, {"nbr": "NBR 6122"}),
            ],
        ),
        # ── 03 Fundacoes (Foundations) - NBR 6122 ────────────────────────
        (
            "03",
            "Fundações (Foundations) - NBR 6122",
            {"nbr": "NBR 6122"},
            [
                ("03.001", "Estaca raiz / hidráulica d=80cm sob torre (Bored/root pile)", "m", 6800, 285.00, {"nbr": "NBR 6122"}),
                ("03.002", "Estaca hélice contínua d=70cm subsolos (CFA pile)", "m", 5200, 248.00, {"nbr": "NBR 6122"}),
                ("03.003", "Mobilização de equipamento de estaca (Piling rig mob)", "vb", 1, 145000.00, {"sinapi": "EQUIP"}),
                ("03.004", "Arrasamento de cabeça de estaca (Pile head trimming)", "un", 320, 165.00, {"sinapi": "96528"}),
                ("03.005", "Concreto fck 40 MPa para blocos de coroamento (Pile-cap concrete)", "m3", 2400, 695.00, {"nbr": "NBR 6118"}),
                ("03.006", "Forma de madeira para blocos e vigas baldrame (Formwork)", "m2", 5800, 88.00, {"sinapi": "92410"}),
                ("03.007", "Armadura aco CA-50 em fundação (Reinforcing steel CA-50)", "kg", 285000, 13.20, {"nbr": "NBR 7480"}),
                ("03.008", "Vigas baldrame em concreto armado (RC ground beams)", "m3", 680, 760.00, {"nbr": "NBR 6118"}),
                ("03.009", "Impermeabilização de baldrame e blocos com manta asfáltica (Waterproofing)", "m2", 4200, 62.00, {"nbr": "NBR 9575"}),
                ("03.010", "Lastro de concreto magro fck 15 MPa (Lean concrete blinding)", "m3", 340, 495.00, {"nbr": "NBR 6118"}),
            ],
        ),
        # ── 04 Estrutura de concreto armado (RC superstructure) ──────────
        (
            "04",
            "Estrutura de Concreto Armado (RC structure) - NBR 6118",
            {"nbr": "NBR 6118"},
            [
                ("04.001", "Concreto usinado fck 50 MPa bombeado - pilares/núcleo (Pumped concrete)", "m3", 9800, 695.00, {"nbr": "NBR 6118"}),
                ("04.002", "Concreto usinado fck 40 MPa bombeado - vigas (Beam concrete)", "m3", 6400, 648.00, {"nbr": "NBR 6118"}),
                ("04.003", "Concreto usinado fck 35 MPa bombeado - lajes (Slab concrete)", "m3", 14500, 615.00, {"nbr": "NBR 6118"}),
                ("04.004", "Forma de madeira compensada plastificada - lajes/vigas (Plywood formwork)", "m2", 96000, 98.00, {"sinapi": "92433"}),
                ("04.005", "Forma metálica reaproveitável de pilar e núcleo (Steel column/core forms)", "m2", 18500, 128.00, {"sinapi": "92444"}),
                ("04.006", "Armadura aco CA-50 - pilares, vigas e lajes (Reinforcing steel CA-50)", "kg", 1850000, 13.40, {"nbr": "NBR 7480"}),
                ("04.007", "Armadura aco CA-60 telas e estribos (Steel CA-60 mesh/stirrups)", "kg", 420000, 13.90, {"nbr": "NBR 7480"}),
                ("04.008", "Cordoalha de protensão nao aderente CP-190 - lajes (Unbonded PT tendons)", "kg", 165000, 22.50, {"nbr": "NBR 6118"}),
                ("04.009", "Escoramento metálico de lajes - locação (Slab shoring rental)", "m2", 96000, 42.00, {"sinapi": "ESCORA"}),
                ("04.010", "Concreto fck 30 MPa escadas e patamares (Stairs concrete)", "m3", 480, 648.00, {"nbr": "NBR 6118"}),
                ("04.011", "Tratamento e cura controlada do concreto (Concrete curing)", "m2", 110000, 4.80, {"nbr": "NBR 14931"}),
                ("04.012", "Reservatório inferior e superior em concreto armado (RC water tanks)", "m3", 620, 760.00, {"nbr": "NBR 6118"}),
            ],
        ),
        # ── 05 Alvenaria e vedacoes (Masonry / partitions) ───────────────
        (
            "05",
            "Alvenaria e Vedações (Masonry and partitions)",
            {"sinapi": "ALVENARIA"},
            [
                ("05.001", "Alvenaria de bloco de concreto 14x19x39cm vedação (Concrete block wall)", "m2", 32000, 96.00, {"sinapi": "87505"}),
                ("05.002", "Alvenaria de bloco cerâmico 14x19x39cm áreas internas (Ceramic block wall)", "m2", 18500, 82.00, {"sinapi": "87489"}),
                ("05.003", "Verga e contraverga em concreto armado (Lintels)", "m", 5800, 42.00, {"sinapi": "93183"}),
                ("05.004", "Encunhamento / fixação de alvenaria (Wall pinning)", "m", 8200, 19.50, {"sinapi": "ENCUNHA"}),
                ("05.005", "Divisória de piso a teto em drywall acústico (Acoustic drywall partition)", "m2", 24000, 128.00, {"nbr": "NBR 14715"}),
                ("05.006", "Divisória de pele de vidro interna escritórios (Internal glass partition)", "m2", 6800, 285.00, {"nbr": "NBR 14718"}),
            ],
        ),
        # ── 06 Fachada cortina e esquadrias (Curtain wall / openings) ────
        (
            "06",
            "Fachada Cortina e Esquadrias (Curtain wall and openings)",
            {"nbr": "NBR 10821"},
            [
                ("06.001", "Fachada cortina unitizada pele de vidro - alu e vidro insulado (Unitized curtain wall)", "m2", 22500, 1850.00, {"nbr": "NBR 10821"}),
                ("06.002", "Vidro insulado de controle solar low-e (Solar-control IGU)", "m2", 4200, 685.00, {"nbr": "NBR 7199"}),
                ("06.003", "Brise metálico horizontal de sombreamento (Metal sun-shading brise)", "m2", 3800, 480.00, {"nbr": "NBR 10821"}),
                ("06.004", "Porta giratória automática de entrada do lobby (Automatic revolving entrance)", "un", 3, 145000.00, {"nbr": "NBR 10821"}),
                ("06.005", "Porta de alumínio e vidro temperado lojas térreo (Aluminium glass door)", "m2", 480, 920.00, {"nbr": "NBR 10821"}),
                ("06.006", "Porta corta-fogo P90 escadas e halls (Fire door P90)", "un", 280, 2150.00, {"nbr": "NBR 11742"}),
                ("06.007", "Porta de madeira semi-oca com batente áreas internas (Internal timber door)", "un", 640, 720.00, {"sinapi": "90843"}),
                ("06.008", "Guarda-corpo em vidro temperado e inox (Glass/steel balustrade)", "m", 1850, 580.00, {"nbr": "NBR 14718"}),
                ("06.009", "Corrimão metálico em escadas - NBR 9050 (Handrails)", "m", 1480, 175.00, {"nbr": "NBR 9050"}),
                ("06.010", "Porta de enrolar automatizada acesso de garagem (Roller garage gate)", "un", 4, 22500.00, {"sinapi": "PORTAO"}),
            ],
        ),
        # ── 07 Cobertura e impermeabilizacao (Roof / waterproofing) ──────
        (
            "07",
            "Cobertura e Impermeabilização (Roof and waterproofing)",
            {"nbr": "NBR 9575"},
            [
                ("07.001", "Impermeabilização de laje de cobertura com manta asfáltica 4mm (Roof waterproofing)", "m2", 1850, 92.00, {"nbr": "NBR 9575"}),
                ("07.002", "Impermeabilização de áreas frias e sanitários com membrana (Wet-área waterproofing)", "m2", 8200, 64.00, {"nbr": "NBR 9575"}),
                ("07.003", "Impermeabilização dos 4 subsolos / cortina (Basement tanking)", "m2", 12500, 78.00, {"nbr": "NBR 9575"}),
                ("07.004", "Proteção mecânica de impermeabilização em argamassa (Screed protection)", "m2", 1850, 34.00, {"sinapi": "98557"}),
                ("07.005", "Telhado metálico termoacústico casa de máquinas (Metal roof plant room)", "m2", 980, 175.00, {"nbr": "NBR 8800"}),
                ("07.006", "Calha e rufo em chapa de alumínio (Aluminium gutters/flashing)", "m", 680, 118.00, {"sinapi": "94228"}),
                ("07.007", "Isolamento térmico em la de rocha na cobertura (Thermal insulation)", "m2", 1850, 56.00, {"sinapi": "ISOL"}),
            ],
        ),
        # ── 08 Revestimentos, pisos e forros (Finishes) ──────────────────
        (
            "08",
            "Revestimentos, Pisos e Forros (Renders, floors, ceilings)",
            {"sinapi": "REVESTIMENTO"},
            [
                ("08.001", "Chapisco em paredes internas e externas (Spatterdash render)", "m2", 95000, 10.80, {"sinapi": "87878"}),
                ("08.002", "Emboço / massa única interna desempenada (Internal plaster)", "m2", 72000, 42.00, {"sinapi": "87529"}),
                ("08.003", "Contrapiso em argamassa e=5cm áreas comuns (Floor screed)", "m2", 38000, 46.00, {"sinapi": "87703"}),
                ("08.004", "Piso elevado técnico modular escritórios (Raised access floor)", "m2", 31000, 285.00, {"nbr": "NBR 11802"}),
                ("08.005", "Piso porcelanato 90x90cm lobby e áreas comuns (Porcelain floor tile)", "m2", 9800, 185.00, {"sinapi": "87265"}),
                ("08.006", "Revestimento cerâmico de parede áreas molhadas (Wall tiling)", "m2", 12500, 92.00, {"sinapi": "87263"}),
                ("08.007", "Forro mineral acústico modular escritórios (Acoustic mineral ceiling)", "m2", 31000, 128.00, {"nbr": "NBR 14715"}),
                ("08.008", "Forro em gesso acartonado áreas comuns (Plasterboard ceiling)", "m2", 9800, 78.00, {"nbr": "NBR 14715"}),
                ("08.009", "Piso de alta resistência nos subsolos com endurecedor (Garage floor)", "m2", 38000, 72.00, {"sinapi": "PISO IND"}),
                ("08.010", "Soleira, peitoril e bancada em granito (Granite thresholds/countertops)", "m2", 1850, 580.00, {"sinapi": "98674"}),
                ("08.011", "Piso tátil de alerta e direcional - acessibilidade (Tactile paving)", "m2", 680, 165.00, {"nbr": "NBR 9050"}),
            ],
        ),
        # ── 09 Instalacoes hidrossanitarias e incendio (Plumbing/fire) ───
        (
            "09",
            "Instalações Hidrossanitárias e Incêndio (Plumbing / fire) - NBR 5626",
            {"nbr": "NBR 5626"},
            [
                ("09.001", "Tubulação de água fria PVC/PPR soldável (Cold water piping)", "m", 14500, 32.00, {"nbr": "NBR 5626"}),
                ("09.002", "Tubulação de água quente CPVC áreas técnicas (Hot water piping)", "m", 3800, 46.00, {"nbr": "NBR 7198"}),
                ("09.003", "Tubulação de esgoto e ventilação PVC série reforçada (Drainage/vent)", "m", 12800, 42.00, {"nbr": "NBR 8160"}),
                ("09.004", "Tubulação de águas pluviais PVC e ferro fundido (Rainwater piping)", "m", 4800, 58.00, {"nbr": "NBR 10844"}),
                ("09.005", "Louça sanitária suspensa com válvula de descarga (WC suite)", "un", 280, 720.00, {"sinapi": "86888"}),
                ("09.006", "Lavatório de bancada com cuba e metais (Washbasin + fittings)", "un", 280, 580.00, {"sinapi": "86901"}),
                ("09.007", "Sistema de reuso de águas cinzas com tratamento (Greywater reuse)", "vb", 1, 320000.00, {"nbr": "NBR 5626"}),
                ("09.008", "Reservatório de incêndio e rede de hidrantes (Fire reserve/hydrants)", "vb", 1, 480000.00, {"nbr": "NBR 13714"}),
                ("09.009", "Sistema de chuveiros automáticos sprinklers (Automatic sprinklers)", "m2", 46500, 38.00, {"nbr": "NBR 10897"}),
                ("09.010", "Sistema de pressurização e bombas de recalque (Booster pumps)", "un", 6, 32000.00, {"nbr": "NBR 5626"}),
                ("09.011", "Detecção e alarme de incêndio endereçável (Addressable fire detection)", "m2", 46500, 22.00, {"nbr": "NBR 17240"}),
                ("09.012", "Pressurização de escadas de segurança (Stair pressurisation)", "un", 4, 145000.00, {"nbr": "NBR 9077"}),
            ],
        ),
        # ── 10 Instalacoes eletricas, telecom e SPDA (Electrical) ────────
        (
            "10",
            "Instalações Elétricas, Telecom e SPDA (Electrical / lightning) - NBR 5410",
            {"nbr": "NBR 5410"},
            [
                ("10.001", "Subestação abrigada com transformadores 2x1500kVA (Substation/transformers)", "vb", 1, 1850000.00, {"nbr": "NBR 14039"}),
                ("10.002", "Quadro geral de baixa tensão QGBT (Main LV switchboard)", "un", 2, 185000.00, {"nbr": "NBR 5410"}),
                ("10.003", "Quadro de distribuição por pavimento (Floor distribution boards)", "un", 96, 4800.00, {"nbr": "NBR 5410"}),
                ("10.004", "Eletrocalha e leito para cabos perfilados (Cable tray/ladder)", "m", 18500, 68.00, {"nbr": "NBR 5410"}),
                ("10.005", "Cabo de cobre flexível isolado 0,6/1kV (Copper power cable)", "m", 165000, 9.80, {"nbr": "NBR 5410"}),
                ("10.006", "Luminária LED de embutir com sensor de presença (LED luminaire + sensor)", "un", 8600, 185.00, {"sinapi": "97593"}),
                ("10.007", "Iluminação de emergência e sinalização de rota de fuga (Emergency lighting)", "un", 980, 195.00, {"nbr": "NBR 10898"}),
                ("10.008", "Sistema de proteção contra descargas atmosféricas SPDA (Lightning protection)", "vb", 1, 285000.00, {"nbr": "NBR 5419"}),
                ("10.009", "Aterramento e equalização de potenciais (Earthing/bonding)", "vb", 1, 145000.00, {"nbr": "NBR 5419"}),
                ("10.010", "Cabeamento estruturado cat.6A e backbone de fibra (Structured cabling)", "m", 96000, 11.50, {"nbr": "NBR 14565"}),
                ("10.011", "CFTV IP e controle de acesso predial (IP CCTV/access control)", "vb", 1, 685000.00, {"nbr": "NBR 14565"}),
                ("10.012", "Automação predial BMS e gestão de energia (Building mgmt system)", "vb", 1, 980000.00, {"nbr": "NBR 16280"}),
                ("10.013", "Ponto de recarga de veículo elétrico nos subsolos (EV charging point)", "un", 80, 7200.00, {"nbr": "NBR 17019"}),
                ("10.014", "Grupo gerador a diesel standby 2x750kVA (Standby generators)", "un", 2, 685000.00, {"nbr": "NBR 5410"}),
            ],
        ),
        # ── 11 Climatizacao AVAC e elevadores (HVAC / lifts) ─────────────
        (
            "11",
            "Climatização (AVAC) e Elevadores (HVAC and lifts) - NBR 16401",
            {"nbr": "NBR 16401"},
            [
                ("11.001", "Central de água gelada com chiller centrífugo 800TR (Centrifugal chiller)", "un", 2, 1850000.00, {"nbr": "NBR 16401"}),
                ("11.002", "Torre de resfriamento de água de condensação (Cooling tower)", "un", 3, 285000.00, {"nbr": "NBR 16401"}),
                ("11.003", "Fan-coil de teto para lajes de escritório (Ceiling fan-coil units)", "un", 220, 14500.00, {"nbr": "NBR 16401"}),
                ("11.004", "Rede de dutos de ar em chapa galvanizada (Galvanised ductwork)", "kg", 185000, 18.50, {"nbr": "NBR 16401"}),
                ("11.005", "Tubulação hidráulica de água gelada isolada (Insulated chilled-water piping)", "m", 6800, 145.00, {"nbr": "NBR 16401"}),
                ("11.006", "Ventilação mecânica e exaustão dos subsolos (Garage ventilation/CO)", "vb", 1, 685000.00, {"nbr": "NBR 16401"}),
                ("11.007", "Difusores, grelhas e dampers corta-fogo (Diffusers/fire dampers)", "un", 4200, 285.00, {"nbr": "NBR 16401"}),
                ("11.008", "Balanceamento, testes e comissionamento do AVAC (HVAC commissioning)", "vb", 1, 485000.00, {"nbr": "NBR 16401"}),
                ("11.009", "Elevador corporativo de alta velocidade 1600kg (High-speed passenger lift)", "un", 6, 985000.00, {"nbr": "NBR NM 207"}),
                ("11.010", "Elevador de serviço/acessível 2000kg (Service/accessible lift)", "un", 2, 1150000.00, {"nbr": "NBR 9050"}),
            ],
        ),
        # ── 12 Servicos complementares e areas externas (Complementary) ──
        (
            "12",
            "Serviços Complementares e Áreas Externas (Complementary / external works)",
            {"sinapi": "COMPLEMENTAR"},
            [
                ("12.001", "Pintura látex acrílica interna 2 demãos (Internal acrylic paint)", "m2", 95000, 19.50, {"sinapi": "88489"}),
                ("12.002", "Massa corrida PVA em paredes internas (Internal filler)", "m2", 72000, 15.50, {"sinapi": "88485"}),
                ("12.003", "Pintura epóxi de piso e demarcação nos subsolos (Epoxy garage paint)", "m2", 38000, 36.00, {"sinapi": "EPOXI"}),
                ("12.004", "Paisagismo, jardins e irrigação das áreas externas (Landscaping/irrigation)", "m2", 1850, 165.00, {"sinapi": "PAISAG"}),
                ("12.005", "Pavimentação de piso intertravado no passeio (Interlocking paving)", "m2", 1450, 96.00, {"sinapi": "92396"}),
                ("12.006", "Drenagem de águas pluviais e caixas de areia externas (External drainage)", "m", 980, 118.00, {"nbr": "NBR 10844"}),
                ("12.007", "Limpeza final de obra e entrega (Final cleaning/handover)", "m2", 46500, 9.80, {"sinapi": "9537"}),
                ("12.008", "As-built, testes e comissionamento integrado (Commissioning/as-built)", "vb", 1, 285000.00, {"sinapi": "COMISS"}),
                ("12.009", "Consultoria e certificação LEED Core & Shell (LEED certification)", "vb", 1, 480000.00, {"sinapi": "LEED"}),
            ],
        ),
    ],
    markups=[
        # BDI brasileiro decomposto sobre o custo direto (obra comercial RJ).
        ("Administração central (Central overhead)", 4.5, "overhead", "direct_cost"),
        ("Despesas financeiras (Financial costs)", 1.5, "overhead", "direct_cost"),
        ("Riscos e imprevistos (Risk/contingency)", 2.0, "contingency", "direct_cost"),
        ("Lucro / Benefício (Profit)", 7.5, "profit", "direct_cost"),
        ("ISS Rio de Janeiro (Municipal service tax)", 5.0, "tax", "cumulative"),
    ],
    total_months=32,
    tender_name="Estrutura e Fundações (Structure and foundations)",
    tender_companies=[
        ("Construtora Belmiro Varandes (Varonel)", "licitação@varonel.example", 0.98),
        ("Andravel Costeira Engenharia", "obras@andravel.example", 1.03),
        ("Construtora Tavaredo", "propostas@tavaredo.example", 1.01),
    ],
    project_metadata={
        "address": "Avenida Rodrigues Alves 250, Porto Maravilha, Centro, Rio de Janeiro - RJ, 20220-360",
        "client": "Vardanto Empreendimentos Imobiliários Ltda.",
        "architect": "Andrelli/Vasconde Arquitetos",
        "structural_engineer": "Ferrandes e Associados Engenharia",
        "gfa_m2": 46500,
        "storeys": 22,
        "basements": 4,
        "parking_spaces": 480,
        "floor_plate_m2": 1450,
        "building_class": "Corporativo AAA (escritórios)",
        "structure_system": "Concreto armado moldado in loco com lajes protendidas (NBR 6118)",
        "foundation": "Estaca raiz e hélice contínua (NBR 6122)",
        "facade_system": "Fachada cortina unitizada (pele de vidro) com vidro insulado de controle solar",
        "standards": [
            "NBR 6118 (projeto de estruturas de concreto)",
            "NBR 6122 (fundações)",
            "NBR 15575 (desempenho de edificações habitacionais e comerciais)",
            "NBR 8800 (estruturas de aco)",
            "NBR 9050 (acessibilidade)",
            "NBR 5410 (instalações elétricas de baixa tensão)",
            "NBR 5419 (SPDA - proteção contra descargas atmosféricas)",
            "NBR 5626 (instalação predial de água fria)",
            "NBR 16401 (instalações de ar-condicionado - sistemas centrais)",
            "NBR 9575 (impermeabilização)",
            "NBR 9077 (saidas de emergência em edificios)",
        ],
        "cost_reference": "SINAPI Desonerado RJ (CAIXA/IBGE), base 2026-01",
        "bdi_note": (
            "BDI (Beneficios e Despesas Indiretas) aplicado sobre o custo direto; "
            "decomposto em administração central, despesas financeiras, risco e lucro."
        ),
        "tax_note": (
            "ISS (Imposto Sobre Serviços) municipal do Rio de Janeiro a 5% sobre o "
            "valor dos serviços, conforme legislação do município. PIS/COFINS e "
            "demais tributos federais ja considerados no regime desonerado SINAPI."
        ),
        "procurement_note": (
            "Contratação regida pela Lei 14.133/2021 (nova lei de licitações) "
            "quando aplicável a recursos públicos; obra privada por contrato direto."
        ),
        "sustainability": "Certificação LEED Core & Shell pretendida (nível ouro)",
        "regulator": "Prefeitura do Rio de Janeiro - Secretaria de Urbanismo (SMU)",
        "permit_note": (
            "Licença de obras pela Prefeitura do Rio de Janeiro; aprovação do "
            "projeto de incêndio e laudo (AVCB/COE) junto ao Corpo de Bombeiros do "
            "Estado do Rio de Janeiro (CBMERJ); operação urbana consorciada Porto "
            "Maravilha; habite-se ao final."
        ),
    },
    tender_packages=[
        (
            "Estrutura e Fundações (Structure and foundations)",
            "Movimento de terra, contenção, estacas, blocos, concreto armado, protensão e formas",
            "evaluating",
            [
                ("Construtora Belmiro Varandes (Varonel)", "licitação@varonel.example", 0.98),
                ("Andravel Costeira Engenharia", "obras@andravel.example", 1.03),
                ("Construtora Tavaredo", "propostas@tavaredo.example", 1.01),
            ],
        ),
        (
            "Fachada e Esquadrias (Facade and openings)",
            "Fachada cortina unitizada, pele de vidro, brises, esquadrias e portas",
            "evaluating",
            [
                ("Marveto Engenharia", "comercial@marveto.example", 0.99),
                ("Prumaz Engenharia", "licitação@prumaz.example", 1.04),
                ("Clanmere Group Brasil", "propostas@clanmere-br.example", 1.02),
            ],
        ),
        (
            "Instalações Hidráulicas, Elétricas e Incêndio (MEP)",
            "Instalações hidrossanitárias, elétricas, SPDA, telecom, BMS e incêndio",
            "evaluating",
            [
                ("Predivex Instalações Prediais", "obras@predivex.example", 0.97),
                ("Geravolt Engenharia", "propostas@geravolt.example", 1.05),
                ("Andravel Costeira Engenharia", "instalações@andravel.example", 1.03),
            ],
        ),
        (
            "Climatização AVAC (HVAC central plant)",
            "Central de água gelada, chillers, torres, fan-coils, dutos e comissionamento",
            "evaluating",
            [
                ("Klimavor do Brasil", "obra@klimavor.example", 0.98),
                ("Frigenta Brasil", "propostas@frigenta.example", 1.04),
                ("Toriwara Cooling & Heating Brasil", "comercial@toriwara.example", 1.02),
            ],
        ),
        (
            "Elevadores (Vertical transportation)",
            "Fornecimento e montagem de elevadores de alta velocidade e despacho inteligente",
            "evaluating",
            [
                ("Belventa Elevadores", "obra@belventa.example", 0.98),
                ("Elvantis Elevadores Brasil", "propostas@elvantis-br.example", 1.05),
                ("Rhenwerk Elevadores", "comercial@rhenwerk.example", 1.02),
            ],
        ),
        (
            "Acabamentos e Áreas Comuns (Finishes and fit-out)",
            "Revestimentos, pisos elevados, forros, pintura, paisagismo e áreas externas",
            "evaluating",
            [
                ("Construval CVPS", "propostas@construval.example", 0.98),
                ("Vandelo Engenharia", "comercial@vandelo.example", 1.04),
                ("Marveto Engenharia", "licitação@marveto.example", 1.01),
            ],
        ),
    ],
    budget_boq_name="Orçamento Sintético Corporativo - Padrão SINAPI",
    planned_budget=420000000.00,
    actual_spend_ratio=0.42,
    spi_override=0.97,
    cpi_override=1.02,
)
