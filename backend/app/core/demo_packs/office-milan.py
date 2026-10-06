# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: italy-voci - Edificio direzionale, Milano (Office building, Milan)
# ---------------------------------------------------------------------------
# An Italian estimate is a computo metrico estimativo: measured quantities
# against an elenco prezzi. This bill follows the same methodology as the
# Rome residential demo but covers a mid-rise commercial office building
# in the Porta Nuova district of Milan.
#
# The same caveats from the Rome demo apply here: the voce codes are
# correctly shaped but not published, the rates are direct cost net of
# spese generali and utile, and the statutory references must be
# recomputed for the actual site before the bill goes near a tender.
#
# IVA is 22 per cent because that is the standard rate for commercial
# construction. Spese generali and utile d'impresa are added as markup
# lines, so the unit rates are the listed price divided by 1.265.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-milan",
    project_name="Edificio direzionale Porta Nuova - Milano (Office Building, Milan)",
    project_description=(
        "Nuova costruzione di un edificio direzionale di 8 piani fuori terra e "
        "3 piani interrati destinati ad autorimessa e locali tecnici, nel quartiere "
        "Porta Nuova, Milano. Superficie lorda complessiva circa 14.600 mq, di cui "
        "circa 10.200 mq fuori terra e 4.400 mq interrati. Struttura a telaio in "
        "acciaio con nuclei in cemento armato, fondazione su pali trivellati e platea. "
        "Facciata continua a cellule in vetro e alluminio, classificazione energetica A4, "
        "impianti a pompa di calore geotermica con fotovoltaico in copertura. "
        "Computo metrico estimativo redatto sul prezzario della Camera di Commercio di "
        "Milano, livello prezzi Milano 2026, importo dei lavori circa 28,5 milioni di euro "
        "oltre IVA. "
        "New-build 8-storey office building with 3 basement levels of parking and "
        "plant in the Porta Nuova district of Milan. Gross area approx. 14,600 m2 "
        "(approx. 10,200 m2 above ground, 4,400 m2 below). Steel frame with RC "
        "cores on bored piles and a raft. Unitised aluminium and glass curtain wall, "
        "energy class A4, ground-source heat pump services with rooftop photovoltaics. "
        "Measured works approx. EUR 28.5 million excluding VAT."
    ),
    region="IT",
    classification_standard="voci",
    currency="EUR",
    locale="it",
    project_code="MI-PNU-2026-01",
    address={
        "street": "Via Melchiorre Gioia 22",
        "city": "Milano",
        "postcode": "20124",
        "country": "Italy",
        "lat": 45.4847,
        "lng": 9.1905,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    boq_name="Computo metrico estimativo - Prezzario Camera di Commercio Milano (Bill of Quantities)",
    boq_description=(
        "Computo metrico estimativo per categorie di lavoro, redatto sull'elenco prezzi "
        "della Camera di Commercio di Milano e integrato con analisi dei prezzi per le "
        "voci non presenti. I prezzi unitari esposti sono costi diretti al netto di "
        "spese generali e utile d'impresa. Livello prezzi Milano 2026, IVA esclusa. "
        "Bill of quantities by work category on the Milan Chamber of Commerce price "
        "book. Unit rates are direct cost net of overheads and profit. Milan 2026 "
        "price level, VAT excluded."
    ),
    boq_metadata={
        "standard": "Prezzario Camera di Commercio di Milano",
        "phase": "Progetto esecutivo - computo metrico estimativo (Detailed design estimate)",
        "base_date": "2026-Q1",
        "price_level": "Milano 2026 (Milan 2026)",
        "pricing_method": "Computo metrico estimativo su elenco prezzi, costi diretti al netto di spese generali e utile",
    },
    sections=[
        (
            "A",
            "Cap. A - Opere provvisionali e allestimento del cantiere (Temporary works and site set-up)",
            {"voci": "A"},
            [
                (
                    "A.1",
                    "Recinzione di cantiere in pannelli grigliati h 2,20 m con cancelli carrabili e pedonali (Site hoarding with vehicle and pedestrian gates)",
                    "m",
                    280.0,
                    28.50,
                    {"voci": "A.01.010.a"},
                ),
                (
                    "A.2",
                    "Baraccamenti di cantiere: uffici, spogliatoi, servizi igienici e refettorio (Site accommodation, offices and welfare)",
                    "mese",
                    30.0,
                    2_250.00,
                    {"voci": "A.01.030.b"},
                ),
                (
                    "A.3",
                    "Ponteggio metallico a telai prefabbricati fino a 32 m di altezza (Tube and frame scaffold, 18 month hire)",
                    "m2",
                    8_400.0,
                    22.50,
                    {"voci": "A.02.010.a"},
                ),
                (
                    "A.4",
                    "Gru a torre a rotazione alta, braccio 55 m, portata in punta 2,0 t (Tower crane, 55 m jib, 2.0 t tip load)",
                    "mese",
                    24.0,
                    5_200.00,
                    {"voci": "A.02.030.c"},
                ),
                (
                    "A.5",
                    "Impianto elettrico e idrico di cantiere con quadri ASC e illuminazione (Temporary site power, water and lighting)",
                    "a corpo",
                    1.0,
                    82_000.00,
                    {"voci": "A.03.010.a"},
                ),
                (
                    "A.6",
                    "Montacarichi da cantiere a colonna, portata 1000 kg (Mast climbing material hoist 1000 kg)",
                    "mese",
                    18.0,
                    1_580.00,
                    {"voci": "A.02.050.a"},
                ),
                (
                    "A.7",
                    "Gestione ambientale del cantiere e smaltimento rifiuti (Site environmental management and waste disposal)",
                    "mese",
                    30.0,
                    1_680.00,
                    {"voci": "A.03.030.b"},
                ),
            ],
        ),
        (
            "B",
            "Cap. B - Scavi, movimenti terra e opere di fondazione (Earthworks and foundations)",
            {"voci": "B"},
            [
                (
                    "B.1",
                    "Scavo di sbancamento con mezzi meccanici (Bulk excavation, machine, loaded to lorry)",
                    "m3",
                    19_800.0,
                    7.20,
                    {"voci": "B.01.010.a"},
                ),
                (
                    "B.2",
                    "Scavo a sezione obbligata per plinti e travi rovesce (Trench and pit excavation)",
                    "m3",
                    2_150.0,
                    13.80,
                    {"voci": "B.01.020.b"},
                ),
                (
                    "B.3",
                    "Trasporto dei materiali di risulta a discarica autorizzata (Haulage and licensed tipping of spoil)",
                    "m3",
                    18_500.0,
                    15.80,
                    {"voci": "B.01.040.a"},
                ),
                (
                    "B.4",
                    "Paratia di micropali e jet-grouting per il sostegno dello scavo (Micropile and jet-grout retaining wall)",
                    "m2",
                    2_200.0,
                    168.00,
                    {"voci": "B.02.010.c"},
                ),
                (
                    "B.5",
                    "Pali trivellati D 800 mm, calcestruzzo C28/35 (Bored piles D800, C28/35)",
                    "m",
                    5_400.0,
                    88.00,
                    {"voci": "B.03.010.a"},
                ),
                (
                    "B.6",
                    "Magrone di sottofondazione C12/15 spessore 10 cm (Blinding concrete C12/15)",
                    "m3",
                    185.0,
                    108.00,
                    {"voci": "B.04.010.a"},
                ),
                (
                    "B.7",
                    "Rinterro e rinfianco con materiale arido di cava (Granular backfill, compacted in layers)",
                    "m3",
                    3_600.0,
                    19.50,
                    {"voci": "B.05.010.b"},
                ),
                (
                    "B.8",
                    "Vespaio areato con casseri modulari a cupola h 50 cm (Ventilated void former slab 500 mm)",
                    "m2",
                    2_400.0,
                    42.50,
                    {"voci": "B.04.030.a"},
                ),
                (
                    "B.9",
                    "Drenaggio perimetrale con tubo PEAD D 200 mm e ghiaia lavata (Perimeter land drain, HDPE pipe and washed gravel)",
                    "m",
                    240.0,
                    46.00,
                    {"voci": "B.05.030.a"},
                ),
            ],
        ),
        (
            "C",
            "Cap. C - Strutture in acciaio e cemento armato (Steel and RC structure)",
            {"voci": "C"},
            [
                (
                    "C.1",
                    "Platea di fondazione C32/40 XC2 spessore 80 cm (Raft foundation C32/40 XC2, 800 mm)",
                    "m3",
                    1_350.0,
                    138.00,
                    {"voci": "C.01.010.a"},
                ),
                (
                    "C.2",
                    "Muri controterra C32/40 XC2 con additivo idrofugo, spessore 40 cm (Basement retaining walls C32/40, waterproof admixture)",
                    "m3",
                    580.0,
                    162.00,
                    {"voci": "C.01.030.b"},
                ),
                (
                    "C.3",
                    "Nuclei di controvento e vani ascensore in c.a. C35/45 (RC shear cores and lift shafts C35/45)",
                    "m3",
                    420.0,
                    172.00,
                    {"voci": "C.02.010.a"},
                ),
                (
                    "C.4",
                    "Carpenteria metallica primaria: colonne e travi HE e IPE in S355 (Primary steelwork, columns and beams S355)",
                    "t",
                    680.0,
                    3_850.00,
                    {"voci": "C.02.020.a"},
                ),
                (
                    "C.5",
                    "Solette composte acciaio-calcestruzzo con lamiera grecata e connettori (Composite steel-concrete floor, profiled deck with shear studs)",
                    "m2",
                    10_200.0,
                    82.00,
                    {"voci": "C.03.010.b"},
                ),
                (
                    "C.6",
                    "Scale interne in acciaio e cemento armato (Cast in-situ RC and steel stairs)",
                    "m3",
                    145.0,
                    248.00,
                    {"voci": "C.03.040.a"},
                ),
                (
                    "C.7",
                    "Acciaio in barre B450C sagomato e posto in opera (Reinforcement B450C, cut, bent and fixed)",
                    "kg",
                    620_000.0,
                    1.52,
                    {"voci": "C.04.010.a"},
                ),
                (
                    "C.8",
                    "Casseforme per getti verticali e orizzontali (Formwork to vertical and horizontal elements)",
                    "m2",
                    12_800.0,
                    27.50,
                    {"voci": "C.04.030.b"},
                ),
                (
                    "C.9",
                    "Protezione antincendio passiva R120 della carpenteria metallica con vernici intumescenti (Intumescent fire protection R120 to steelwork)",
                    "m2",
                    8_500.0,
                    32.00,
                    {"voci": "C.05.010.a"},
                ),
                (
                    "C.10",
                    "Prove sui materiali e controlli di accettazione (Materials testing and acceptance controls)",
                    "a corpo",
                    1.0,
                    58_000.00,
                    {"voci": "C.06.010.a"},
                ),
            ],
        ),
        (
            "D",
            "Cap. D - Tamponamenti, divisori e compartimentazioni (Infill walls, partitions and compartmentation)",
            {"voci": "D"},
            [
                (
                    "D.1",
                    "Tamponamento perimetrale in blocchi di laterizio porizzato 30 cm (Perimeter infill wall, porous clay blocks 300 mm)",
                    "m2",
                    4_800.0,
                    56.00,
                    {"voci": "D.01.010.a"},
                ),
                (
                    "D.2",
                    "Tramezzature in lastre di gesso rivestito su orditura metallica (Plasterboard partitions on metal studs)",
                    "m2",
                    6_800.0,
                    38.50,
                    {"voci": "D.01.030.b"},
                ),
                (
                    "D.3",
                    "Pareti mobili vetrate per uffici open-space (Glazed demountable partitions for open-plan offices)",
                    "m2",
                    3_200.0,
                    285.00,
                    {"voci": "D.02.010.a"},
                ),
                (
                    "D.4",
                    "Contropareti isolanti su murature perimetrali (Insulated internal linings to external walls)",
                    "m2",
                    4_600.0,
                    36.00,
                    {"voci": "D.02.030.a"},
                ),
                (
                    "D.5",
                    "Compartimentazioni antincendio REI 120 ai cavedi e filtri (Fire compartmentation REI 120 to risers and lobbies)",
                    "m2",
                    1_650.0,
                    72.00,
                    {"voci": "D.04.010.a"},
                ),
                (
                    "D.6",
                    "Muratura in blocchi di calcestruzzo per locali tecnici (Concrete block walls to plant rooms)",
                    "m2",
                    2_400.0,
                    44.00,
                    {"voci": "D.01.050.a"},
                ),
            ],
        ),
        (
            "E",
            "Cap. E - Involucro: facciata continua, copertura e impermeabilizzazioni (Envelope, curtain wall, roofing and waterproofing)",
            {"voci": "E"},
            [
                (
                    "E.1",
                    "Facciata continua a cellule in vetro e alluminio a taglio termico, Ucw non superiore a 1,1 W/m2K (Unitised curtain wall, aluminium and glass, Ucw <= 1.1 W/m2K)",
                    "m2",
                    5_800.0,
                    520.00,
                    {"voci": "E.04.010.c"},
                ),
                (
                    "E.2",
                    "Pannelli di rivestimento opachi in alluminio composito per fasce marcapiano e parapetti (Aluminium composite cladding panels to spandrels)",
                    "m2",
                    1_800.0,
                    185.00,
                    {"voci": "E.03.030.a"},
                ),
                (
                    "E.3",
                    "Impermeabilizzazione della copertura con doppia membrana bituminosa 4+4 mm (Two-layer bituminous roof waterproofing)",
                    "m2",
                    1_650.0,
                    29.50,
                    {"voci": "E.01.030.b"},
                ),
                (
                    "E.4",
                    "Isolamento termico della copertura in XPS 160 mm (Roof thermal insulation, XPS 160 mm)",
                    "m2",
                    1_650.0,
                    28.80,
                    {"voci": "E.02.010.a"},
                ),
                (
                    "E.5",
                    "Impermeabilizzazione delle strutture controterra (Below-grade tanking with protection board)",
                    "m2",
                    3_400.0,
                    33.00,
                    {"voci": "E.02.030.a"},
                ),
                (
                    "E.6",
                    "Isolamento a cappotto dei muri perimetrali ciechi in EPS grafite 160 mm (External wall insulation, graphite EPS 160 mm)",
                    "m2",
                    2_400.0,
                    68.00,
                    {"voci": "E.03.010.b"},
                ),
                (
                    "E.7",
                    "Frangisole motorizzati in alluminio estruso per le facciate sud e ovest (Motorised aluminium louvred sunscreens, south and west facades)",
                    "m2",
                    2_200.0,
                    248.00,
                    {"voci": "E.04.030.a"},
                ),
                (
                    "E.8",
                    "Opere da lattoniere: scossaline, converse e pluviali in acciaio inox (Stainless steel flashings, gutters and downpipes)",
                    "m",
                    1_450.0,
                    38.50,
                    {"voci": "E.05.010.a"},
                ),
                (
                    "E.9",
                    "Lucernari in copertura con vetrocamera basso emissivo e apertura motorizzata (Rooflights, low-e double glazing, motorised opening)",
                    "m2",
                    180.0,
                    680.00,
                    {"voci": "E.04.050.a"},
                ),
                (
                    "E.10",
                    "Sistemi anticaduta permanenti di copertura (Permanent roof fall arrest systems)",
                    "m",
                    320.0,
                    72.00,
                    {"voci": "E.05.030.a"},
                ),
            ],
        ),
        (
            "F",
            "Cap. F - Finiture interne e opere di completamento (Internal finishes)",
            {"voci": "F"},
            [
                (
                    "F.1",
                    "Massetto autolivellante a base anidritica spessore 7 cm con materassino acustico (Self-levelling anhydrite screed 70 mm with acoustic underlay)",
                    "m2",
                    10_200.0,
                    26.50,
                    {"voci": "F.01.030.b"},
                ),
                (
                    "F.2",
                    "Pavimento sopraelevato h 15 cm con pannelli rivestiti in gres per uffici (Raised access floor 150 mm with porcelain finish)",
                    "m2",
                    8_500.0,
                    92.00,
                    {"voci": "F.02.010.a"},
                ),
                (
                    "F.3",
                    "Pavimento in gres porcellanato 60x60 cm per atri e corridoi (Porcelain floor tiles 600x600 to lobbies and corridors)",
                    "m2",
                    1_850.0,
                    52.00,
                    {"voci": "F.02.030.b"},
                ),
                (
                    "F.4",
                    "Rivestimento in gres porcellanato per servizi igienici (Porcelain wall tiling to toilets)",
                    "m2",
                    3_200.0,
                    48.50,
                    {"voci": "F.02.050.a"},
                ),
                (
                    "F.5",
                    "Controsoffitti in pannelli di fibra minerale 600x600 su orditura a vista (Mineral fibre suspended ceiling 600x600 exposed grid)",
                    "m2",
                    8_200.0,
                    34.50,
                    {"voci": "F.05.010.b"},
                ),
                (
                    "F.6",
                    "Controsoffitti in lastre di gesso rivestito per servizi igienici (Plasterboard ceilings to toilets)",
                    "m2",
                    2_400.0,
                    32.00,
                    {"voci": "F.05.030.a"},
                ),
                (
                    "F.7",
                    "Tinteggiatura con idropittura traspirante a due mani (Two-coat breathable emulsion on primer)",
                    "m2",
                    28_000.0,
                    8.20,
                    {"voci": "F.03.010.a"},
                ),
                (
                    "F.8",
                    "Porte interne tamburate a filo muro con serratura a badge (Internal flush doors, frameless, with badge lock)",
                    "cad",
                    280.0,
                    485.00,
                    {"voci": "F.04.010.c"},
                ),
                (
                    "F.9",
                    "Porte tagliafuoco REI 60 e REI 120 in acciaio con maniglione antipanico (Steel fire doors REI 60 and REI 120 with panic hardware)",
                    "cad",
                    85.0,
                    1_280.00,
                    {"voci": "F.04.030.a"},
                ),
                (
                    "F.10",
                    "Rivestimento in pietra naturale dell'atrio di ingresso (Natural stone cladding to entrance lobby)",
                    "m2",
                    480.0,
                    185.00,
                    {"voci": "F.06.010.a"},
                ),
                (
                    "F.11",
                    "Arredi fissi della reception e del front desk in legno e acciaio (Built-in reception and front desk furniture)",
                    "a corpo",
                    1.0,
                    92_000.00,
                    {"voci": "F.06.030.b"},
                ),
            ],
        ),
        (
            "G",
            "Cap. G - Impianti idrico-sanitari, di climatizzazione e ventilazione (Plumbing, HVAC and ventilation)",
            {"voci": "G"},
            [
                (
                    "G.1",
                    "Rete di adduzione idrica con collettori e contabilizzazione per piano (Water distribution with floor manifolds and metering)",
                    "m",
                    3_200.0,
                    32.50,
                    {"voci": "G.01.010.a"},
                ),
                (
                    "G.2",
                    "Rete di scarico in polipropilene fonoassorbente (Acoustic polypropylene drainage)",
                    "m",
                    2_800.0,
                    28.50,
                    {"voci": "G.01.030.b"},
                ),
                (
                    "G.3",
                    "Apparecchi sanitari sospesi per servizi igienici di piano (Wall-hung sanitaryware to floor toilets)",
                    "cad",
                    180.0,
                    520.00,
                    {"voci": "G.02.010.a"},
                ),
                (
                    "G.4",
                    "Pompa di calore geotermica acqua-acqua da 400 kW (Water-to-water GSHP 400 kW)",
                    "cad",
                    2.0,
                    185_000.00,
                    {"voci": "G.03.030.a"},
                ),
                (
                    "G.5",
                    "Sonde geotermiche verticali, profondita 120 m (Vertical ground loops, 120 m deep)",
                    "m",
                    4_800.0,
                    52.00,
                    {"voci": "G.03.030.b"},
                ),
                (
                    "G.6",
                    "Fan-coil a cassetta per controsoffitto con valvola a due vie (Ceiling cassette fan-coil units with 2-way valve)",
                    "cad",
                    320.0,
                    1_280.00,
                    {"voci": "G.03.010.c"},
                ),
                (
                    "G.7",
                    "Unita di trattamento aria primaria con recuperatore rotativo (Primary AHU with rotary heat recovery)",
                    "cad",
                    4.0,
                    68_000.00,
                    {"voci": "G.04.010.b"},
                ),
                (
                    "G.8",
                    "Canalizzazioni aerauliche in lamiera zincata con isolamento (Galvanised steel ductwork with insulation)",
                    "m2",
                    6_200.0,
                    42.50,
                    {"voci": "G.04.030.a"},
                ),
                (
                    "G.9",
                    "Ventilazione ed estrazione fumi dell'autorimessa interrata (Basement car park ventilation and smoke extract)",
                    "a corpo",
                    1.0,
                    195_000.00,
                    {"voci": "G.04.050.a"},
                ),
                (
                    "G.10",
                    "Sistema di regolazione BMS con supervisione centralizzata (BMS with centralised supervision)",
                    "a corpo",
                    1.0,
                    285_000.00,
                    {"voci": "G.05.010.a"},
                ),
                (
                    "G.11",
                    "Coibentazione delle tubazioni e collaudi funzionali (Pipe insulation and commissioning)",
                    "a corpo",
                    1.0,
                    68_000.00,
                    {"voci": "G.06.010.a"},
                ),
            ],
        ),
        (
            "H",
            "Cap. H - Impianti elettrici, speciali, antincendio ed elevatori (Electrical, ELV, fire systems and lifts)",
            {"voci": "H"},
            [
                (
                    "H.1",
                    "Cabina di trasformazione MT/BT 800 kVA con quadri e protezioni (MV/LV substation 800 kVA)",
                    "a corpo",
                    1.0,
                    185_000.00,
                    {"voci": "H.01.010.a"},
                ),
                (
                    "H.2",
                    "Distribuzione elettrica primaria e quadri generali di piano (Main electrical distribution and floor boards)",
                    "a corpo",
                    1.0,
                    320_000.00,
                    {"voci": "H.01.030.b"},
                ),
                (
                    "H.3",
                    "Distribuzione secondaria per postazioni ufficio, compresi canali nel pavimento sopraelevato (Secondary power distribution, floor boxes in raised floor)",
                    "cad",
                    480.0,
                    285.00,
                    {"voci": "H.01.050.a"},
                ),
                (
                    "H.4",
                    "Impianto di illuminazione a LED con sensori di presenza e daylight (LED lighting with presence and daylight sensors)",
                    "m2",
                    10_200.0,
                    38.00,
                    {"voci": "H.01.070.b"},
                ),
                (
                    "H.5",
                    "Impianto fotovoltaico in copertura 120 kWp con inverter e accumulo (Rooftop PV array 120 kWp with inverters and storage)",
                    "kWp",
                    120.0,
                    1_320.00,
                    {"voci": "H.03.010.a"},
                ),
                (
                    "H.6",
                    "Impianto di terra e protezione contro le scariche atmosferiche (Earthing, bonding and lightning protection)",
                    "a corpo",
                    1.0,
                    78_000.00,
                    {"voci": "H.02.010.a"},
                ),
                (
                    "H.7",
                    "Rete dati strutturata Cat. 6A con armadi di piano (Structured cabling Cat. 6A with floor cabinets)",
                    "cad",
                    480.0,
                    148.00,
                    {"voci": "H.03.030.a"},
                ),
                (
                    "H.8",
                    "Impianto di rivelazione incendi con centrale analogica indirizzata (Analogue addressable fire detection and alarm)",
                    "a corpo",
                    1.0,
                    148_000.00,
                    {"voci": "H.04.010.b"},
                ),
                (
                    "H.9",
                    "Rete idranti e naspi UNI 45 con gruppo di pressurizzazione antincendio (Fire hydrant and hose reel system with fire pump set)",
                    "a corpo",
                    1.0,
                    165_000.00,
                    {"voci": "H.04.030.a"},
                ),
                (
                    "H.10",
                    "Ascensori elettrici senza locale macchine 1000 kg, 11 fermate (Machine room less lifts 1000 kg, 11 stops)",
                    "cad",
                    4.0,
                    42_000.00,
                    {"voci": "H.05.010.c"},
                ),
                (
                    "H.11",
                    "Punti di ricarica per veicoli elettrici 22 kW con bilanciamento carichi (EV charging points 22 kW with load balancing)",
                    "cad",
                    32.0,
                    1_450.00,
                    {"voci": "H.03.050.a"},
                ),
                (
                    "H.12",
                    "Controllo accessi, videosorveglianza e antintrusione (Access control, CCTV and intruder alarm)",
                    "a corpo",
                    1.0,
                    185_000.00,
                    {"voci": "H.03.070.a"},
                ),
            ],
        ),
        (
            "I",
            "Cap. I - Opere esterne, urbanizzazioni e sistemazioni a verde (External works, services and landscaping)",
            {"voci": "I"},
            [
                (
                    "I.1",
                    "Pavimentazione carrabile in masselli autobloccanti 8 cm (Block paving 80 mm on granular sub-base)",
                    "m2",
                    1_450.0,
                    35.50,
                    {"voci": "I.01.010.a"},
                ),
                (
                    "I.2",
                    "Rampe di accesso all'autorimessa in conglomerato bituminoso (Bituminous paving to car park ramps)",
                    "m2",
                    850.0,
                    23.50,
                    {"voci": "I.01.030.b"},
                ),
                (
                    "I.3",
                    "Reti di sottoservizi per fognatura, acquedotto, energia e telecomunicazioni (External services, drainage, water, power and telecoms)",
                    "m",
                    480.0,
                    148.00,
                    {"voci": "I.02.010.a"},
                ),
                (
                    "I.4",
                    "Vasca di laminazione e impianto trattamento acque di prima pioggia (Stormwater attenuation and first flush treatment)",
                    "a corpo",
                    1.0,
                    135_000.00,
                    {"voci": "I.02.030.a"},
                ),
                (
                    "I.5",
                    "Sistemazione a verde con alberature ad alto fusto e irrigazione automatica (Soft landscaping, trees and automatic irrigation)",
                    "m2",
                    1_800.0,
                    34.50,
                    {"voci": "I.04.010.a"},
                ),
                (
                    "I.6",
                    "Arredi esterni: panchine, rastrelliere biciclette e illuminazione (Site furniture, benches, cycle racks and external lighting)",
                    "a corpo",
                    1.0,
                    92_000.00,
                    {"voci": "I.04.030.b"},
                ),
            ],
        ),
    ],
    markups=[
        ("Spese generali 15 per cento (General overheads)", 15.0, "overhead", "direct_cost"),
        ("Utile d'impresa 10 per cento (Contractor's profit)", 10.0, "profit", "cumulative"),
        (
            "Oneri della sicurezza non soggetti a ribasso (Safety costs, not subject to discount)",
            2.5,
            "other",
            "direct_cost",
        ),
        ("IVA 22 per cento (VAT at 22 percent)", 22.0, "tax", "cumulative"),
    ],
    total_months=28,
    tender_name="Appalto generale opere edili e impianti (Main contract, building and services)",
    tender_companies=[
        ("Costruzioni Lombarde Riunite S.p.A.", "gare@lombarderiunite.example", 0.97),
        ("Impresa Edile Navigli S.r.l.", "appalti@navigli.example", 1.04),
        ("Consorzio Edile Porta Nuova", "gare@consorzioportanuova.example", 1.01),
    ],
    budget_boq_name="Quadro economico di controllo - Milano Porta Nuova (Control Budget)",
    planned_budget=28_500_000.0,
    actual_spend_ratio=0.42,
    spi_override=0.98,
    cpi_override=1.02,
    project_metadata={
        "address": "Via Melchiorre Gioia 22, 20124 Milano, Italia",
        "client": "Immobiliare Porta Nuova Sviluppo S.r.l.",
        "architect": "Studio di Architettura Naviglio Grande Associati",
        "structural_engineer": "Studio di Ingegneria Strutturale Lambrate",
        "quantity_surveyor": "Studio di computo metrico e contabilita Brera",
        "gfa_m2": 14600,
        "gfa_above_ground_m2": 10200,
        "site_area_m2": 4200,
        "storeys": "8 piani fuori terra, 3 piani interrati (8 above ground, 3 basements)",
        "basement_levels": 3,
        "building_height_m": 33.6,
        "parking_spaces": 185,
        "structure_system": "Telaio in acciaio S355 con nuclei in cemento armato e solette composte",
        "energy_performance": (
            "Edificio a energia quasi zero, classificazione energetica A4, impianti a "
            "pompa di calore geotermica e fotovoltaico in copertura."
        ),
        "pricing_standard": "Prezzario Camera di Commercio di Milano",
        "estimating_method": ("Computo metrico estimativo su elenco prezzi della Camera di Commercio di Milano."),
        "vat_note": (
            "IVA al 22 per cento, aliquota ordinaria per costruzioni commerciali. "
            "I subappalti nel settore edile sono soggetti a inversione contabile."
        ),
    },
    # The price list every line is cited from, so the Italian voce rules read
    # the list's own numbering as such. The codes illustrate that numbering;
    # they are not copied from the published list. The rates are direct cost,
    # net of the spese generali and utile carried as markups, which
    # rate_includes_overheads states so they are not taken as counted twice.
    # The quadro economico carries the same safety line as the bill: the costs
    # not subject to the tender discount stand apart in both.
    budget_markups=[
        (
            "Oneri della sicurezza non soggetti a ribasso (Safety costs, not subject to discount)",
            2.5,
            "other",
            "direct_cost",
        ),
    ],
    position_metadata={
        "prezzario": {
            "region": "Lombardia",
            "region_code": "LOM",
            "edition": "2026",
            "rate_includes_overheads": False,
            "list": "Prezzario Camera di Commercio di Milano",
        }
    },
)
