from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: Edificio Residencial Sao Paulo (brazil-sinapi)
# ---------------------------------------------------------------------------
# Orcamento sintetico no padrao brasileiro (SINAPI / NBR) para um predio
# residencial em concreto armado na cidade de Sao Paulo. Precos a nivel
# Sao Paulo 2026 (referencia SINAPI Desonerado SP), moeda BRL, locale pt-BR.
# Composicoes citam codigos SINAPI representativos e normas NBR aplicaveis.
# Classification_standard "masterformat" e usado apenas como fallback de
# plataforma; cada item carrega codigo SINAPI e/ou NBR no dicionario de
# classificacao.

TEMPLATE = DemoTemplate(
    demo_id="residential-saopaulo",
    project_name="Edificio Residencial Jardins - Sao Paulo",
    project_description=(
        "Construcao de edificio residencial multifamiliar em concreto armado, "
        "1 torre com 18 pavimentos-tipo + terreo (pilotis) + 2 subsolos de "
        "garagem. 144 unidades (apartamentos de 2 e 3 dormitorios). "
        "Area de terreno ~2.100 m2, area construida total (ABC) ~10.800 m2. "
        "Estrutura em concreto armado convencional moldado in loco (NBR 6118), "
        "lajes nervuradas, fundacao profunda em estacas helice continua. "
        "Acessibilidade NBR 9050, SPDA NBR 5419, certificacao GBC Brasil Casa "
        "(nivel prata pretendido). Custo de obra (custo direto) ~R$ 35 milhoes."
    ),
    region="BR",
    classification_standard="masterformat",
    currency="BRL",
    locale="pt-BR",
    address={
        "street": "Rua Oscar Freire 1200",
        "city": "Sao Paulo",
        "postcode": "01426-001",
        "country": "Brazil",
        "lat": -23.5614,
        "lng": -46.6722,
    },
    validation_rule_sets=["sinapi", "nbr", "boq_quality", "project_completeness"],
    boq_name="Orcamento Sintetico - Padrao SINAPI",
    boq_description=(
        "Orcamento sintetico por etapas conforme pratica brasileira, "
        "composicoes referenciadas ao SINAPI (CAIXA/IBGE) Sao Paulo, "
        "desonerado. BDI aplicado sobre o custo direto."
    ),
    boq_metadata={
        "standard": "SINAPI / NBR (orcamento sintetico)",
        "phase": "Projeto executivo - orcamento de obra",
        "base_date": "2026-01",
        "price_level": "Sao Paulo (SP) 2026 - SINAPI Desonerado",
    },
    sections=[
        # ── 01 Servicos preliminares (Preliminary / general services) ────
        (
            "01",
            "Servicos Preliminares e Canteiro (Preliminaries / site setup)",
            {"sinapi": "SERV. PRELIMINARES"},
            [
                ("01.001", "Placa de obra em chapa galvanizada 4,0x2,0m (Site signboard)", "m2", 8, 380.00, {"sinapi": "74209/001"}),
                ("01.002", "Tapume em chapa compensado resinado h=2,20m (Hoarding)", "m2", 480, 95.00, {"sinapi": "73604"}),
                ("01.003", "Barracao de obra / canteiro em chapa madeirite (Site office/sheds)", "m2", 220, 520.00, {"sinapi": "73847/001"}),
                ("01.004", "Ligacao provisoria de agua e esgoto (Temporary water/sewer)", "lsum", 1, 12000.00, {"sinapi": "98459"}),
                ("01.005", "Ligacao provisoria de energia eletrica trifasica (Temporary power)", "lsum", 1, 18500.00, {"sinapi": "98460"}),
                ("01.006", "Locacao da obra com gabarito de tabuas (Setting out)", "m2", 1900, 14.50, {"sinapi": "74077/001"}),
                ("01.007", "Mobilizacao e desmobilizacao de equipamentos (Mob/demob)", "lsum", 1, 45000.00, {"sinapi": "ADMIN"}),
                ("01.008", "Limpeza permanente da obra (Continuous site cleaning)", "month", 26, 4800.00, {"sinapi": "97644"}),
                ("01.009", "Equipamento de protecao coletiva / NR-18 (Collective safety)", "lsum", 1, 68000.00, {"nbr": "NR-18"}),
                ("01.010", "Grua fixa torre - locacao mensal (Tower crane rental)", "month", 16, 28000.00, {"sinapi": "EQUIP"}),
            ],
        ),
        # ── 02 Movimento de terra e contencao (Earthworks/shoring) ───────
        (
            "02",
            "Movimento de Terra e Contencao (Earthworks and shoring)",
            {"sinapi": "MOV. TERRA"},
            [
                ("02.001", "Escavacao mecanizada subsolos (Mechanical excavation)", "m3", 14500, 18.50, {"sinapi": "90082"}),
                ("02.002", "Carga, transporte e bota-fora ate 10km DMT (Haul/disposal)", "m3", 16000, 32.00, {"sinapi": "93590"}),
                ("02.003", "Cortina de estaca-prancha / parede diafragma (Diaphragm wall)", "m2", 1850, 420.00, {"nbr": "NBR 6122"}),
                ("02.004", "Tirantes ancorados protendidos (Ground anchors)", "m", 720, 165.00, {"nbr": "NBR 5629"}),
                ("02.005", "Rebaixamento de lencol freatico / drenagem (Dewatering)", "lsum", 1, 95000.00, {"sinapi": "DRENAGEM"}),
                ("02.006", "Reaterro apiloado em camadas com compactacao (Backfill)", "m3", 2400, 28.00, {"sinapi": "93382"}),
                ("02.007", "Lastro de brita apiloado e=10cm (Gravel bed)", "m2", 1900, 22.50, {"sinapi": "96617"}),
            ],
        ),
        # ── 03 Fundacoes (Foundations) ───────────────────────────────────
        (
            "03",
            "Fundacoes (Foundations) - NBR 6122",
            {"nbr": "NBR 6122"},
            [
                ("03.001", "Estaca helice continua d=50cm (Continuous flight auger pile)", "m", 2800, 168.00, {"nbr": "NBR 6122"}),
                ("03.002", "Estaca helice continua d=60cm (CFA pile)", "m", 1600, 215.00, {"nbr": "NBR 6122"}),
                ("03.003", "Mobilizacao de equipamento de estaca (Piling rig mob)", "lsum", 1, 38000.00, {"sinapi": "EQUIP"}),
                ("03.004", "Arrasamento de cabeca de estaca (Pile head trimming)", "pcs", 96, 145.00, {"sinapi": "96528"}),
                ("03.005", "Concreto fck 30 MPa para blocos de coroamento (Pile caps concrete)", "m3", 420, 595.00, {"nbr": "NBR 6118"}),
                ("03.006", "Forma de madeira para blocos e vigas baldrame (Formwork)", "m2", 1850, 78.00, {"sinapi": "92410"}),
                ("03.007", "Armadura aco CA-50 em fundacao (Reinforcing steel CA-50)", "kg", 52000, 12.80, {"nbr": "NBR 7480"}),
                ("03.008", "Vigas baldrame em concreto armado (Ground beams)", "m3", 180, 720.00, {"nbr": "NBR 6118"}),
                ("03.009", "Impermeabilizacao de baldrame com manta asfaltica (Waterproofing)", "m2", 1200, 58.00, {"nbr": "NBR 9575"}),
                ("03.010", "Lastro de concreto magro fck 15 MPa (Lean concrete blinding)", "m3", 95, 480.00, {"nbr": "NBR 6118"}),
            ],
        ),
        # ── 04 Estrutura de concreto armado (RC superstructure) ──────────
        (
            "04",
            "Estrutura de Concreto Armado (RC structure) - NBR 6118",
            {"nbr": "NBR 6118"},
            [
                ("04.001", "Concreto usinado fck 35 MPa bombeado - pilares/vigas (Pumped concrete)", "m3", 3200, 615.00, {"nbr": "NBR 6118"}),
                ("04.002", "Concreto usinado fck 30 MPa bombeado - lajes (Slab concrete)", "m3", 2400, 585.00, {"nbr": "NBR 6118"}),
                ("04.003", "Forma de madeira compensada plastificada - lajes/vigas (Plywood formwork)", "m2", 28000, 92.00, {"sinapi": "92433"}),
                ("04.004", "Forma de pilar em chapa metalica reaproveitavel (Column steel forms)", "m2", 4200, 118.00, {"sinapi": "92444"}),
                ("04.005", "Armadura aco CA-50 - pilares e vigas (Reinforcing steel CA-50)", "kg", 285000, 13.20, {"nbr": "NBR 7480"}),
                ("04.006", "Armadura aco CA-60 telas e estribos (Steel CA-60 mesh/stirrups)", "kg", 95000, 13.80, {"nbr": "NBR 7480"}),
                ("04.007", "Escoramento metalico de lajes - locacao (Slab shoring rental)", "m2", 28000, 38.00, {"sinapi": "ESCORA"}),
                ("04.008", "Cubas plasticas para laje nervurada (Ribbed slab void formers)", "m2", 12000, 24.00, {"nbr": "NBR 6118"}),
                ("04.009", "Concreto fck 25 MPa escadas e patamares (Stairs concrete)", "m3", 145, 595.00, {"nbr": "NBR 6118"}),
                ("04.010", "Tratamento e cura do concreto (Concrete curing)", "m2", 32000, 4.20, {"nbr": "NBR 14931"}),
                ("04.011", "Junta de dilatacao com perfil e selante (Expansion joints)", "m", 320, 95.00, {"nbr": "NBR 6118"}),
                ("04.012", "Reservatorio inferior/superior em concreto armado (RC water tanks)", "m3", 220, 720.00, {"nbr": "NBR 6118"}),
            ],
        ),
        # ── 05 Alvenaria e vedacoes (Masonry / partitions) ───────────────
        (
            "05",
            "Alvenaria e Vedacoes (Masonry and partitions)",
            {"sinapi": "ALVENARIA"},
            [
                ("05.001", "Alvenaria de bloco ceramico vedacao 14x19x39cm (Ceramic block wall)", "m2", 18500, 78.00, {"sinapi": "87489"}),
                ("05.002", "Alvenaria de bloco de concreto 14x19x39cm (Concrete block wall)", "m2", 4200, 92.00, {"sinapi": "87505"}),
                ("05.003", "Verga e contraverga em concreto armado (Lintels)", "m", 3600, 38.00, {"sinapi": "93183"}),
                ("05.004", "Encunhamento / fixacao de alvenaria (Wall pinning)", "m", 4800, 18.50, {"sinapi": "ENCUNHA"}),
                ("05.005", "Divisoria leve em drywall acustico (Acoustic drywall partition)", "m2", 5200, 118.00, {"nbr": "NBR 14715"}),
                ("05.006", "Forro em gesso acartonado (Plasterboard ceiling)", "m2", 9200, 68.00, {"nbr": "NBR 14715"}),
                ("05.007", "Tela de fachada para reforco de revestimento (Facade mesh)", "m2", 6800, 14.50, {"sinapi": "TELA"}),
            ],
        ),
        # ── 06 Cobertura e impermeabilizacao (Roof / waterproofing) ──────
        (
            "06",
            "Cobertura e Impermeabilizacao (Roof and waterproofing)",
            {"nbr": "NBR 9575"},
            [
                ("06.001", "Impermeabilizacao de laje de cobertura com manta asfaltica 4mm (Roof waterproofing)", "m2", 1850, 88.00, {"nbr": "NBR 9575"}),
                ("06.002", "Impermeabilizacao de areas frias / banheiros com membrana (Wet area waterproofing)", "m2", 4200, 62.00, {"nbr": "NBR 9575"}),
                ("06.003", "Protecao mecanica de impermeabilizacao em argamassa (Screed protection)", "m2", 1850, 32.00, {"sinapi": "98557"}),
                ("06.004", "Telhado metalico termoacustico sobre casa de maquinas (Metal roof)", "m2", 420, 165.00, {"nbr": "NBR 8800"}),
                ("06.005", "Calha e rufo em chapa galvanizada (Gutters/flashing)", "m", 380, 95.00, {"sinapi": "94228"}),
                ("06.006", "Isolamento termico em la de rocha cobertura (Thermal insulation)", "m2", 1850, 48.00, {"sinapi": "ISOL"}),
            ],
        ),
        # ── 07 Revestimentos e pisos (Renders / floor finishes) ──────────
        (
            "07",
            "Revestimentos, Pisos e Forros (Renders, floors, ceilings)",
            {"sinapi": "REVESTIMENTO"},
            [
                ("07.001", "Chapisco em paredes internas e externas (Spatterdash render)", "m2", 38000, 9.80, {"sinapi": "87878"}),
                ("07.002", "Emboco / massa unica interna desempenada (Internal plaster)", "m2", 28000, 38.00, {"sinapi": "87529"}),
                ("07.003", "Reboco de fachada com argamassa industrializada (Facade render)", "m2", 6800, 52.00, {"sinapi": "87534"}),
                ("07.004", "Revestimento ceramico de parede 30x60cm areas molhadas (Wall tiling)", "m2", 8400, 88.00, {"sinapi": "87263"}),
                ("07.005", "Contrapiso em argamassa e=4cm (Floor screed)", "m2", 9200, 42.00, {"sinapi": "87703"}),
                ("07.006", "Piso porcelanato 60x60cm areas comuns/unidades (Porcelain floor tile)", "m2", 8800, 135.00, {"sinapi": "87265"}),
                ("07.007", "Piso vinilico em manta apartamentos (Vinyl flooring)", "m2", 2400, 95.00, {"sinapi": "VINIL"}),
                ("07.008", "Soleira e rodape em granito (Granite thresholds/skirting)", "m", 3600, 58.00, {"sinapi": "98689"}),
                ("07.009", "Piso de alta resistencia garagem com endurecedor (Garage floor)", "m2", 5200, 68.00, {"sinapi": "PISO IND"}),
                ("07.010", "Bancada e soleira em granito banheiros/cozinha (Granite countertops)", "m2", 620, 480.00, {"sinapi": "98674"}),
                ("07.011", "Piso tatil de alerta/direcional - acessibilidade (Tactile paving)", "m2", 280, 145.00, {"nbr": "NBR 9050"}),
            ],
        ),
        # ── 08 Esquadrias (Doors, windows, frames) ───────────────────────
        (
            "08",
            "Esquadrias e Vidros (Doors, windows, glazing)",
            {"sinapi": "ESQUADRIAS"},
            [
                ("08.001", "Porta de madeira semi-oca 80x210cm com batente (Internal timber door)", "pcs", 720, 680.00, {"sinapi": "90843"}),
                ("08.002", "Porta corta-fogo P90 escadas/halls (Fire door P90)", "pcs", 42, 1850.00, {"nbr": "NBR 11742"}),
                ("08.003", "Esquadria de aluminio com vidro - janela maxim-ar (Aluminium window)", "m2", 3200, 720.00, {"nbr": "NBR 10821"}),
                ("08.004", "Porta de aluminio e vidro de sacada de correr (Sliding balcony door)", "m2", 1680, 850.00, {"nbr": "NBR 10821"}),
                ("08.005", "Guarda-corpo em vidro temperado sacadas (Glass balustrade)", "m", 1480, 480.00, {"nbr": "NBR 14718"}),
                ("08.006", "Porta de enrolar / portao garagem automatizado (Roller garage gate)", "pcs", 2, 18500.00, {"sinapi": "PORTAO"}),
                ("08.007", "Corrimao metalico em escadas - NBR 9050 (Handrails)", "m", 680, 165.00, {"nbr": "NBR 9050"}),
                ("08.008", "Espelho e box em vidro temperado banheiros (Glass shower/mirror)", "pcs", 288, 420.00, {"nbr": "NBR 14488"}),
            ],
        ),
        # ── 09 Instalacoes hidrossanitarias (Plumbing) ───────────────────
        (
            "09",
            "Instalacoes Hidrossanitarias (Plumbing / sanitary)",
            {"nbr": "NBR 5626"},
            [
                ("09.001", "Tubulacao de agua fria PVC soldavel (Cold water piping)", "m", 6200, 28.00, {"nbr": "NBR 5626"}),
                ("09.002", "Tubulacao de agua quente CPVC (Hot water piping)", "m", 2800, 42.00, {"nbr": "NBR 7198"}),
                ("09.003", "Tubulacao de esgoto e ventilacao PVC serie normal (Drainage/vent)", "m", 5400, 38.00, {"nbr": "NBR 8160"}),
                ("09.004", "Tubulacao de aguas pluviais PVC (Rainwater piping)", "m", 1800, 42.00, {"nbr": "NBR 10844"}),
                ("09.005", "Louca sanitaria - bacia com caixa acoplada (WC suite)", "pcs", 200, 580.00, {"sinapi": "86888"}),
                ("09.006", "Lavatorio com coluna / cuba e metais (Washbasin + fittings)", "pcs", 200, 480.00, {"sinapi": "86901"}),
                ("09.007", "Conjunto de chuveiro e registros (Shower set)", "pcs", 200, 320.00, {"sinapi": "89957"}),
                ("09.008", "Pia de cozinha inox com torneira (Kitchen sink)", "pcs", 144, 680.00, {"sinapi": "86914"}),
                ("09.009", "Tanque de lavanderia e torneira (Laundry tub)", "pcs", 144, 380.00, {"sinapi": "86915"}),
                ("09.010", "Reservatorio de incendio e sistema de hidrantes (Fire reserve/hydrants)", "lsum", 1, 145000.00, {"nbr": "NBR 13714"}),
                ("09.011", "Sistema de pressurizacao / bombas de recalque (Booster pumps)", "pcs", 4, 18500.00, {"nbr": "NBR 5626"}),
                ("09.012", "Aquecimento solar de agua com coletores (Solar water heating)", "m2", 220, 980.00, {"nbr": "NBR 15569"}),
                ("09.013", "Medicao individualizada de agua por unidade (Individual water metering)", "pcs", 144, 680.00, {"nbr": "NBR 5626"}),
            ],
        ),
        # ── 10 Instalacoes eletricas e SPDA (Electrical / lightning) ─────
        (
            "10",
            "Instalacoes Eletricas, Telecom e SPDA (Electrical / lightning)",
            {"nbr": "NBR 5410"},
            [
                ("10.001", "Quadro de distribuicao geral de baixa tensao QGBT (Main LV board)", "pcs", 1, 48000.00, {"nbr": "NBR 5410"}),
                ("10.002", "Quadro de distribuicao por unidade / pavimento (Distribution boards)", "pcs", 162, 1850.00, {"nbr": "NBR 5410"}),
                ("10.003", "Eletroduto e conexoes PVC corrugado (Conduit)", "m", 42000, 8.50, {"nbr": "NBR 5410"}),
                ("10.004", "Cabo de cobre flexivel isolado 750V (Copper cable)", "m", 96000, 6.80, {"nbr": "NBR 5410"}),
                ("10.005", "Tomadas, interruptores e espelhos (Sockets/switches)", "pcs", 5800, 38.00, {"nbr": "NBR 5410"}),
                ("10.006", "Luminaria LED de embutir areas comuns (LED luminaires)", "pcs", 1200, 145.00, {"sinapi": "97593"}),
                ("10.007", "Iluminacao de emergencia e sinalizacao de rota de fuga (Emergency lighting)", "pcs", 320, 185.00, {"nbr": "NBR 10898"}),
                ("10.008", "Sistema de protecao contra descargas atmosfericas SPDA (Lightning protection)", "lsum", 1, 92000.00, {"nbr": "NBR 5419"}),
                ("10.009", "Aterramento e equalizacao de potenciais (Earthing/bonding)", "lsum", 1, 38000.00, {"nbr": "NBR 5419"}),
                ("10.010", "Infraestrutura de cabeamento estruturado e CFTV (Structured cabling/CCTV)", "m", 18000, 9.50, {"nbr": "NBR 14565"}),
                ("10.011", "Interfone e controle de acesso por unidade (Intercom/access control)", "pcs", 144, 480.00, {"sinapi": "INTERFONE"}),
                ("10.012", "Ponto de recarga de veiculo eletrico garagem (EV charging point)", "pcs", 24, 6800.00, {"nbr": "NBR 17019"}),
                ("10.013", "Grupo gerador a diesel standby 250kVA (Standby generator)", "pcs", 1, 185000.00, {"nbr": "NBR 5410"}),
                ("10.014", "Subestacao abrigada / transformador 750kVA (Substation/transformer)", "lsum", 1, 285000.00, {"nbr": "NBR 14039"}),
            ],
        ),
        # ── 11 Elevadores e equipamentos (Lifts / equipment) ─────────────
        (
            "11",
            "Elevadores e Equipamentos (Lifts and equipment)",
            {"nbr": "NBR NM 207"},
            [
                ("11.001", "Elevador de passageiros 8 pessoas / 20 paradas (Passenger lift)", "pcs", 3, 285000.00, {"nbr": "NBR NM 207"}),
                ("11.002", "Elevador de servico/maca acessivel (Service/accessible lift)", "pcs", 1, 320000.00, {"nbr": "NBR 9050"}),
                ("11.003", "Plataforma elevatoria de acessibilidade pilotis (Accessibility platform)", "pcs", 1, 48000.00, {"nbr": "NBR 9050"}),
            ],
        ),
        # ── 12 Pintura (Painting) ────────────────────────────────────────
        (
            "12",
            "Pintura e Acabamentos (Painting and finishes)",
            {"sinapi": "PINTURA"},
            [
                ("12.001", "Massa corrida PVA em paredes internas (Internal filler)", "m2", 26000, 14.50, {"sinapi": "88485"}),
                ("12.002", "Pintura latex acrilica interna 2 demaos (Internal acrylic paint)", "m2", 26000, 18.50, {"sinapi": "88489"}),
                ("12.003", "Pintura de fachada textura acrilica (Facade textured paint)", "m2", 6800, 38.00, {"sinapi": "95626"}),
                ("12.004", "Pintura de forro em latex PVA (Ceiling paint)", "m2", 9200, 16.50, {"sinapi": "88484"}),
                ("12.005", "Pintura epoxi em piso de garagem e demarcacao (Epoxy garage paint)", "m2", 5200, 32.00, {"sinapi": "EPOXI"}),
                ("12.006", "Pintura esmalte em esquadrias e grades metalicas (Enamel on metalwork)", "m2", 1800, 28.00, {"sinapi": "102219"}),
            ],
        ),
        # ── 13 Servicos complementares (Complementary works) ─────────────
        (
            "13",
            "Servicos Complementares e Areas Comuns (Complementary / amenities)",
            {"sinapi": "COMPLEMENTAR"},
            [
                ("13.001", "Paisagismo, jardins e irrigacao (Landscaping/irrigation)", "m2", 850, 145.00, {"sinapi": "PAISAG"}),
                ("13.002", "Piscina em concreto armado com revestimento (RC swimming pool)", "lsum", 1, 285000.00, {"nbr": "NBR 10339"}),
                ("13.003", "Academia, salao de festas e mobiliario fixo (Gym/party room fit-out)", "lsum", 1, 320000.00, {"sinapi": "FITOUT"}),
                ("13.004", "Pavimentacao de piso intertravado areas externas (Interlocking paving)", "m2", 620, 88.00, {"sinapi": "92396"}),
                ("13.005", "Portaria e guarita com automacao de acesso (Concierge/gatehouse)", "lsum", 1, 65000.00, {"sinapi": "GUARITA"}),
                ("13.006", "Drenagem de aguas pluviais e caixas de areia (External drainage)", "m", 480, 95.00, {"nbr": "NBR 10844"}),
                ("13.007", "Sinalizacao de garagem, vagas e acessibilidade (Garage signage)", "lsum", 1, 28000.00, {"nbr": "NBR 9050"}),
                ("13.008", "Limpeza final de obra e entrega (Final cleaning/handover)", "m2", 10800, 8.50, {"sinapi": "9537"}),
                ("13.009", "As-built, testes e comissionamento das instalacoes (Commissioning)", "lsum", 1, 48000.00, {"sinapi": "COMISS"}),
            ],
        ),
    ],
    markups=[
        # BDI brasileiro decomposto sobre o custo direto.
        ("Administracao central (Central overhead)", 4.0, "overhead", "direct_cost"),
        ("Despesas financeiras (Financial costs)", 1.2, "overhead", "direct_cost"),
        ("Riscos e imprevistos (Risk/contingency)", 1.5, "contingency", "direct_cost"),
        ("Lucro / Beneficio (Profit)", 7.0, "profit", "direct_cost"),
        ("ISS Sao Paulo (Municipal service tax)", 5.0, "tax", "cumulative"),
    ],
    total_months=26,
    tender_name="Estrutura e Fundacoes (Structure and foundations)",
    tender_companies=[
        ("Construtora Tenda S.A.", "licitacao@tenda.com.br", 0.99),
        ("Cyrela Construtora", "obras@cyrela.com.br", 1.04),
        ("Construtora Lock", "propostas@construtoralock.com.br", 1.01),
    ],
    project_metadata={
        "address": "Rua Oscar Freire 1200, Jardins, Sao Paulo - SP, 01426-001",
        "client": "Jardins Empreendimentos Imobiliarios Ltda.",
        "architect": "Konigsberger Vannucchi Arquitetos",
        "structural_engineer": "Franca e Associados Engenharia",
        "gfa_m2": 10800,
        "units": 144,
        "storeys": 18,
        "basements": 2,
        "parking_spaces": 188,
        "structure_system": "Concreto armado moldado in loco (NBR 6118)",
        "foundation": "Estaca helice continua (NBR 6122)",
        "standards": [
            "NBR 6118 (projeto de estruturas de concreto)",
            "NBR 6122 (fundacoes)",
            "NBR 8800 (estruturas de aco)",
            "NBR 9050 (acessibilidade)",
            "NBR 5410 (instalacoes eletricas de baixa tensao)",
            "NBR 5419 (SPDA - protecao contra descargas atmosfericas)",
            "NBR 5626 (instalacao predial de agua fria)",
            "NBR 9575 (impermeabilizacao)",
        ],
        "cost_reference": "SINAPI Desonerado SP (CAIXA/IBGE), base 2026-01",
        "bdi_note": (
            "BDI (Beneficios e Despesas Indiretas) aplicado sobre o custo direto; "
            "decomposto em administracao central, despesas financeiras, risco e lucro."
        ),
        "tax_note": (
            "ISS (Imposto Sobre Servicos) municipal de Sao Paulo a 5% sobre o "
            "valor dos servicos, conforme legislacao do municipio. PIS/COFINS e "
            "demais tributos federais ja considerados no regime desonerado SINAPI."
        ),
        "procurement_note": (
            "Contratacao regida pela Lei 14.133/2021 (nova lei de licitacoes) "
            "quando aplicavel a recursos publicos; obra privada por contrato direto."
        ),
        "sustainability": "Certificacao GBC Brasil Casa pretendida (nivel prata)",
        "regulator": "Prefeitura de Sao Paulo - Secretaria de Licenciamento (SEHAB)",
        "permit_note": (
            "Alvara de aprovacao e execucao pela Prefeitura de Sao Paulo; "
            "AVCB junto ao Corpo de Bombeiros (PMESP); habite-se ao final."
        ),
    },
    tender_packages=[
        (
            "Estrutura e Fundacoes (Structure and foundations)",
            "Movimento de terra, contencao, estacas, blocos, concreto armado e formas",
            "evaluating",
            [
                ("Construtora Tenda S.A.", "licitacao@tenda.com.br", 0.99),
                ("Cyrela Construtora", "obras@cyrela.com.br", 1.04),
                ("Construtora Lock", "propostas@construtoralock.com.br", 1.01),
            ],
        ),
        (
            "Vedacoes e Revestimentos (Masonry and finishes)",
            "Alvenaria, drywall, revestimentos, pisos, forros e pintura",
            "evaluating",
            [
                ("MPD Engenharia", "comercial@mpd.com.br", 0.98),
                ("Construcap CCPS", "propostas@construcap.com.br", 1.05),
                ("Racional Engenharia", "licitacao@racional.com.br", 1.02),
            ],
        ),
        (
            "Instalacoes Hidraulicas e Eletricas (MEP)",
            "Instalacoes hidrossanitarias, eletricas, SPDA, telecom e incendio",
            "evaluating",
            [
                ("Engemix Instalacoes", "obras@engemix.com.br", 0.97),
                ("Lock Instalacoes Prediais", "instalacoes@construtoralock.com.br", 1.06),
                ("Tecnogera Engenharia", "propostas@tecnogera.com.br", 1.03),
            ],
        ),
        (
            "Esquadrias e Vidros (Doors, windows, glazing)",
            "Esquadrias de aluminio, vidros, portas, guarda-corpos e box",
            "evaluating",
            [
                ("Aluvidros Esquadrias", "vendas@aluvidros.com.br", 0.99),
                ("Sasazaki Industria", "obra@sasazaki.com.br", 1.04),
                ("Glasstech Vidros", "comercial@glasstech.com.br", 1.01),
            ],
        ),
        (
            "Elevadores (Vertical transportation)",
            "Fornecimento e montagem de elevadores e plataforma de acessibilidade",
            "evaluating",
            [
                ("Atlas Schindler", "obra@schindler.com.br", 0.98),
                ("Otis Elevadores Brasil", "propostas@otis.com.br", 1.05),
                ("ThyssenKrupp Elevadores", "comercial@tke.com.br", 1.02),
            ],
        ),
    ],
)
