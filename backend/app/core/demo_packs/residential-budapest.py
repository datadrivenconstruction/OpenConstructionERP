# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: hungary-hu - Lakóépület, Budapest XIII. kerület
# ---------------------------------------------------------------------------
# A Hungarian building bill is written against the building sectoral item
# order (magasépítési ágazati tételrend): seventeen chapters, a code of the
# shape MA-CC-SSS spread across nine columns, and a cover sheet that totals the
# chapters, adds the contingency and then applies VAT. This bill follows that
# order chapter by chapter, so the chapter numbers below are the item order's
# own and not a numbering invented for the demo.
#
# Two things about a Hungarian bill that a reader from elsewhere gets wrong.
# Every line carries two unit prices, not one: the material (anyag) and the fee
# (díj), and the split is what a subcontract negotiation is actually about. And
# the forint has no subunit in practice, so unit rates are whole numbers; a
# price written with two decimals is a converted figure rather than a Hungarian
# one.
#
# Prices are Budapest 2026 levels in HUF, net of VAT. The platform locale is
# English because the application ships no Hungarian interface bundle, which is
# the same decision the pack manifest records and for the same measured reason.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-budapest",
    project_name="Társasház - Budapest XIII. kerület (Residential Block, Budapest District XIII)",
    project_description=(
        "Új építésű társasház a XIII. kerületi Váci úti fejlesztési tengely mentén: "
        "két lépcsőházas, hét emeletes lakóépület 96 lakással, mélygarázzsal és "
        "üzlethelyiségekkel a földszinten. Monolit vasbeton vázszerkezet, "
        "téglafalazatú kitöltő szerkezetek, lapostető. Az épület a hatályos "
        "energetikai követelmények szerint közel nulla energiaigényű (KNE) "
        "besorolású. Nettó összes szintterület mintegy 11 400 m2. "
        "New-build residential block on the Vaci ut development corridor in "
        "District XIII of Budapest: two stair cores, seven storeys, 96 flats, "
        "an underground car park and ground-floor retail units. Cast in-situ "
        "reinforced concrete frame with masonry infill and a flat roof, built "
        "to the nearly-zero-energy requirement in force. Net floor area "
        "approx. 11,400 m2. Priced at Budapest 2026 levels in forint, net of "
        "VAT."
    ),
    region="HU",
    classification_standard="tetelrend",
    currency="HUF",
    locale="hu",
    address={
        "street": "Váci út 152",
        "city": "Budapest",
        "postcode": "1138",
        "country": "Hungary",
        "lat": 47.5423,
        "lng": 19.0693,
    },
    # ``hungary``, not ``tetelrend``: the latter is the classification
    # standard set above, and naming it here asked the engine for a rule
    # set that does not exist. The engine logs that and carries on, so
    # both Hungarian demos ran the generic quality rules and none of the
    # country's own. The pack manifest had it right all along.
    validation_rule_sets=["hungary", "boq_quality", "project_completeness"],
    boq_name="Költségvetés - magasépítési ágazati tételrend (Bill of Quantities)",
    boq_description=(
        "Fejezetenkénti költségvetés a magasépítési ágazati tételrend szerint. "
        "Minden tétel anyag és díj egységárral szerepel; a fedlapon a tartalék "
        "keret és az áfa a fejezetösszegek után következik. Budapest 2026-os "
        "árszint, nettó forintban. Chapter-by-chapter bill to the building "
        "sectoral item order, every line carrying a material and a fee unit "
        "price, with contingency and VAT applied on the cover sheet after the "
        "chapter totals."
    ),
    boq_metadata={
        "standard": "Magasépítési ágazati tételrend (MA-CC-SSS)",
        "phase": "Kiviteli terv - tenderköltségvetés (Tender bill on construction drawings)",
        "base_date": "2026-Q1",
        "price_level": "Budapest 2026 (HUF, nettó)",
    },
    sections=[
        (
            "MA-01",
            "01 - ÁLTALÁNOS, JÁRULÉKOS KÖLTSÉGEK (General and ancillary costs)",
            {"tetelrend": "MA-01"},
            [
                ("MA-01-11-01", "Felvonulási épületek, irodakonténer és öltöző (Site accommodation)", "hó", 22, 780000, {"tetelrend": "MA-01-11-01"}),
                ("MA-01-11-02", "Ideiglenes közmű kiépítése és fogyasztás (Temporary services and consumption)", "klt", 1, 9600000, {"tetelrend": "MA-01-11-02"}),
                ("MA-01-12-01", "Építési terület körülkerítése, kapuk (Site hoarding and gates)", "m", 310, 34500, {"tetelrend": "MA-01-12-01"}),
                ("MA-01-13-01", "Toronydaru telepítés, bérlet, bontás (Tower crane, hire and dismantling)", "hó", 16, 2450000, {"tetelrend": "MA-01-13-01"}),
                ("MA-01-14-01", "Munkavédelem, egészségvédelmi terv, koordináció (Site safety and coordination)", "klt", 1, 14800000, {"tetelrend": "MA-01-14-01"}),
                ("MA-01-15-01", "Építési napló vezetése, e-építési napló (Construction log, electronic)", "hó", 22, 185000, {"tetelrend": "MA-01-15-01"}),
                ("MA-01-16-01", "Felelős műszaki vezetés (Responsible technical management)", "hó", 22, 950000, {"tetelrend": "MA-01-16-01"}),
                ("MA-01-17-01", "Építési biztosítás és teljesítési garancia (Insurance and performance bond)", "klt", 1, 21500000, {"tetelrend": "MA-01-17-01"}),
            ],
        ),
        (
            "MA-02",
            "02 - ELŐKÉSZÍTŐ MUNKÁK (Preparatory works)",
            {"tetelrend": "MA-02"},
            [
                ("MA-02-11-01", "Terület tisztítása, humuszréteg letermelése (Site clearance and topsoil strip)", "m2", 4200, 1850, {"tetelrend": "MA-02-11-01"}),
                ("MA-02-12-01", "Meglévő burkolatok és alapok bontása (Demolition of existing paving and bases)", "m3", 620, 12400, {"tetelrend": "MA-02-12-01"}),
                ("MA-02-13-01", "Bontási hulladék elszállítása, lerakási díj (Waste haulage and tipping)", "t", 1450, 9800, {"tetelrend": "MA-02-13-01"}),
                ("MA-02-14-01", "Geodéziai kitűzés és kiviteli szintezés (Setting out and levelling)", "klt", 1, 4200000, {"tetelrend": "MA-02-14-01"}),
                ("MA-02-15-01", "Régészeti megfigyelés, szakfelügyelet (Archaeological watching brief)", "nap", 18, 260000, {"tetelrend": "MA-02-15-01"}),
                ("MA-02-16-01", "Közmű kiváltás, egyeztetés a szolgáltatókkal (Utility diversions)", "klt", 1, 18500000, {"tetelrend": "MA-02-16-01"}),
            ],
        ),
        (
            "MA-03",
            "03 - FÖLDMUNKA, ALAPOZÁS (Earthworks and foundations)",
            {"tetelrend": "MA-03"},
            [
                ("MA-03-11-01", "Munkagödör kiemelése géppel, kiszállítással (Bulk excavation, machine, with haulage)", "m3", 21500, 4650, {"tetelrend": "MA-03-11-01"}),
                ("MA-03-11-02", "Kézi földkiemelés szűk helyen (Hand excavation in confined areas)", "m3", 380, 26500, {"tetelrend": "MA-03-11-02"}),
                ("MA-03-12-01", "Résfal készítése, vasalással (Diaphragm wall with reinforcement)", "m2", 3100, 92000, {"tetelrend": "MA-03-12-01"}),
                ("MA-03-12-02", "Talajvízszint süllyesztés a kivitelezés idejére (Dewatering during construction)", "hó", 9, 3850000, {"tetelrend": "MA-03-12-02"}),
                ("MA-03-13-01", "Szerelőbeton C12/15 (Blinding concrete C12/15)", "m3", 240, 46500, {"tetelrend": "MA-03-13-01"}),
                ("MA-03-13-02", "Lemezalap C30/37 XC2, vízzáró (Raft foundation C30/37, watertight)", "m3", 2650, 78500, {"tetelrend": "MA-03-13-02"}),
                ("MA-03-13-03", "Betonacél B500B alapozásban (Reinforcement B500B in foundations)", "t", 318, 465000, {"tetelrend": "MA-03-13-03"}),
                ("MA-03-14-01", "Talajnedvesség elleni szigetelés (Damp-proofing to substructure)", "m2", 3900, 8900, {"tetelrend": "MA-03-14-01"}),
                ("MA-03-15-01", "Visszatöltés tömörítéssel, Trg 95 százalék (Backfill compacted to 95 percent)", "m3", 5400, 5200, {"tetelrend": "MA-03-15-01"}),
            ],
        ),
        (
            "MA-04",
            "04 - SZERKEZETÉPÍTÉSI MUNKÁK (Structural works)",
            {"tetelrend": "MA-04"},
            [
                ("MA-04-11-01", "Monolit vasbeton pillér C30/37 (Cast in-situ RC column C30/37)", "m3", 780, 96500, {"tetelrend": "MA-04-11-01"}),
                ("MA-04-11-02", "Monolit vasbeton fal C30/37 (Cast in-situ RC wall C30/37)", "m3", 2450, 86500, {"tetelrend": "MA-04-11-02"}),
                ("MA-04-12-01", "Monolit vasbeton födém C30/37, 22 cm (Cast in-situ RC slab, 220 mm)", "m2", 11800, 34500, {"tetelrend": "MA-04-12-01"}),
                ("MA-04-12-02", "Monolit vasbeton lépcső és pihenő (RC stairs and landings)", "m3", 165, 118000, {"tetelrend": "MA-04-12-02"}),
                ("MA-04-13-01", "Betonacél B500B felmenő szerkezetben (Reinforcement B500B in superstructure)", "t", 742, 478000, {"tetelrend": "MA-04-13-01"}),
                ("MA-04-14-01", "Zsaluzás rendszerzsaluval, falak és pillérek (System formwork, walls and columns)", "m2", 18600, 6800, {"tetelrend": "MA-04-14-01"}),
                ("MA-04-14-02", "Födémzsaluzás alátámasztással (Slab formwork with propping)", "m2", 12400, 7400, {"tetelrend": "MA-04-14-02"}),
                ("MA-04-15-01", "Kitöltő falazat 30 cm-es kerámia falazóelem (Masonry infill, 300 mm clay block)", "m2", 6800, 19800, {"tetelrend": "MA-04-15-01"}),
                ("MA-04-15-02", "Válaszfal 10 cm-es kerámia falazóelem (Partition, 100 mm clay block)", "m2", 9200, 11400, {"tetelrend": "MA-04-15-02"}),
            ],
        ),
        (
            "MA-05",
            "05 - KÜLSŐ SZAKIPARI MUNKÁK, ÉPÜLET ZÁRÁS (Envelope and external trades)",
            {"tetelrend": "MA-05"},
            [
                ("MA-05-11-01", "Homlokzati hőszigetelő rendszer 16 cm EPS (External wall insulation, 160 mm EPS)", "m2", 7400, 21500, {"tetelrend": "MA-05-11-01"}),
                ("MA-05-11-02", "Homlokzati vékonyvakolat, színezés (Thin-coat render and finish)", "m2", 7400, 6900, {"tetelrend": "MA-05-11-02"}),
                ("MA-05-12-01", "Műanyag nyílászáró háromrétegű üvegezéssel (uPVC window, triple glazed)", "m2", 2150, 138000, {"tetelrend": "MA-05-12-01"}),
                ("MA-05-12-02", "Alumínium portál üzlethelyiségekhez (Aluminium shopfront glazing)", "m2", 420, 245000, {"tetelrend": "MA-05-12-02"}),
                ("MA-05-13-01", "Lapostető rétegrend, PVC vízszigeteléssel (Flat roof build-up, PVC membrane)", "m2", 1750, 32500, {"tetelrend": "MA-05-13-01"}),
                ("MA-05-13-02", "Extenzív zöldtető kialakítása (Extensive green roof)", "m2", 620, 28500, {"tetelrend": "MA-05-13-02"}),
                ("MA-05-14-01", "Erkélykorlát üvegbetéttel (Balcony balustrade with glass infill)", "m", 980, 96000, {"tetelrend": "MA-05-14-01"}),
                ("MA-05-15-01", "Bádogos szerkezetek, párkányok és lefolyók (Sheet metal flashings and downpipes)", "m", 1240, 14500, {"tetelrend": "MA-05-15-01"}),
            ],
        ),
        (
            "MA-06",
            "06 - ÉPÍTÉSZETI, SZAKIPARI MUNKÁK (Architectural and finishing trades)",
            {"tetelrend": "MA-06"},
            [
                ("MA-06-11-01", "Belső vakolat gépi felhordással (Internal plaster, machine applied)", "m2", 34500, 4850, {"tetelrend": "MA-06-11-01"}),
                ("MA-06-11-02", "Glettelés és diszperziós festés két rétegben (Skim and emulsion, two coats)", "m2", 34500, 3200, {"tetelrend": "MA-06-11-02"}),
                ("MA-06-12-01", "Aljzatbeton és úsztatott esztrich (Screed on separating layer)", "m2", 10800, 9800, {"tetelrend": "MA-06-12-01"}),
                ("MA-06-12-02", "Lépéshangszigetelés 3 cm (Impact sound insulation, 30 mm)", "m2", 9600, 5400, {"tetelrend": "MA-06-12-02"}),
                ("MA-06-13-01", "Kerámia burkolat vizes helyiségekben (Ceramic tiling to wet areas)", "m2", 4200, 22500, {"tetelrend": "MA-06-13-01"}),
                ("MA-06-13-02", "Laminált padló lakásokban (Laminate flooring to flats)", "m2", 7200, 14800, {"tetelrend": "MA-06-13-02"}),
                ("MA-06-14-01", "Beltéri ajtó tokkal, szereléssel (Internal door, frame and fitting)", "db", 480, 118000, {"tetelrend": "MA-06-14-01"}),
                ("MA-06-15-01", "Gipszkarton álmennyezet közlekedőkben (Plasterboard ceiling to circulation)", "m2", 1850, 12400, {"tetelrend": "MA-06-15-01"}),
            ],
        ),
        (
            "MA-09",
            "09 - ÉPÜLETGÉPÉSZET (Mechanical services)",
            {"tetelrend": "MA-09"},
            [
                ("MA-09-11-01", "Hőközpont, távhő bekötéssel (Plant room with district heating connection)", "klt", 1, 68500000, {"tetelrend": "MA-09-11-01"}),
                ("MA-09-11-02", "Padlófűtés osztóval, lakásonként (Underfloor heating with manifold, per flat)", "db", 96, 1180000, {"tetelrend": "MA-09-11-02"}),
                ("MA-09-12-01", "Vízellátás alapvezeték és felszálló (Water supply mains and risers)", "m", 2400, 24500, {"tetelrend": "MA-09-12-01"}),
                ("MA-09-12-02", "Szennyvíz ejtővezeték hangcsillapított (Soil stack, acoustic)", "m", 1650, 28500, {"tetelrend": "MA-09-12-02"}),
                ("MA-09-13-01", "Szaniter szerelvények lakásonként (Sanitaryware per flat)", "db", 96, 685000, {"tetelrend": "MA-09-13-01"}),
                ("MA-09-14-01", "Hővisszanyerős szellőzés lakásonként (Heat-recovery ventilation per flat)", "db", 96, 1450000, {"tetelrend": "MA-09-14-01"}),
                ("MA-09-15-01", "Mélygarázs füst- és hőelvezetés (Car park smoke and heat extract)", "klt", 1, 42500000, {"tetelrend": "MA-09-15-01"}),
            ],
        ),
        (
            "MA-11",
            "11 - ERŐSÁRAMÚ MUNKÁK (Electrical power)",
            {"tetelrend": "MA-11"},
            [
                ("MA-11-11-01", "Fogyasztásmérő hely és fő elosztó (Metering position and main board)", "klt", 1, 24500000, {"tetelrend": "MA-11-11-01"}),
                ("MA-11-11-02", "Lakásonkénti elosztó és mérés (Flat consumer unit and metering)", "db", 96, 320000, {"tetelrend": "MA-11-11-02"}),
                ("MA-11-12-01", "Erősáramú kábelezés lakásokban (Power wiring within flats)", "db", 96, 985000, {"tetelrend": "MA-11-12-01"}),
                ("MA-11-13-01", "Közös terek világítása, LED (Communal LED lighting)", "db", 640, 42500, {"tetelrend": "MA-11-13-01"}),
                ("MA-11-14-01", "Villámvédelem és egyenpotenciálra hozás (Lightning protection and bonding)", "klt", 1, 12800000, {"tetelrend": "MA-11-14-01"}),
                ("MA-11-15-01", "Elektromos töltőállomás előkészítés mélygarázsban (EV charging provision in car park)", "db", 24, 485000, {"tetelrend": "MA-11-15-01"}),
            ],
        ),
        (
            "MA-15",
            "15 - FELVONÓK, EMELŐSZERKEZETEK (Lifts and lifting equipment)",
            {"tetelrend": "MA-15"},
            [
                ("MA-15-11-01", "Személyfelvonó 8 személyes, 9 megálló (Passenger lift, 8 person, 9 stops)", "db", 2, 28500000, {"tetelrend": "MA-15-11-01"}),
                ("MA-15-11-02", "Teherfelvonó mélygarázsból (Goods lift from car park)", "db", 1, 21500000, {"tetelrend": "MA-15-11-02"}),
                ("MA-15-12-01", "Felvonó üzembe helyezés, hatósági engedélyezés (Lift commissioning and approval)", "klt", 1, 4800000, {"tetelrend": "MA-15-12-01"}),
            ],
        ),
        (
            "MA-16",
            "16 - KÜLSŐ MUNKÁK (External works)",
            {"tetelrend": "MA-16"},
            [
                ("MA-16-11-01", "Térburkolat betonkővel (Concrete block paving)", "m2", 1850, 18500, {"tetelrend": "MA-16-11-01"}),
                ("MA-16-12-01", "Kertépítés, telepítés és öntözés (Landscaping and irrigation)", "m2", 1420, 14200, {"tetelrend": "MA-16-12-01"}),
                ("MA-16-13-01", "Közműbekötések, víz, csatorna, gáz (Utility connections)", "klt", 1, 34500000, {"tetelrend": "MA-16-13-01"}),
                ("MA-16-14-01", "Kerékpártároló és hulladéktároló (Cycle store and refuse store)", "klt", 1, 9800000, {"tetelrend": "MA-16-14-01"}),
                ("MA-16-15-01", "Kerítés és kapu a telekhatáron (Boundary fence and gate)", "m", 240, 42500, {"tetelrend": "MA-16-15-01"}),
            ],
        ),
        (
            "MA-17",
            "17 - ÁTADÁS (Handover)",
            {"tetelrend": "MA-17"},
            [
                ("MA-17-11-01", "Beszabályozás és próbaüzem (Commissioning and trial operation)", "klt", 1, 12400000, {"tetelrend": "MA-17-11-01"}),
                ("MA-17-12-01", "Megvalósulási dokumentáció és kezelési utasítás (As-built records and O and M manuals)", "klt", 1, 6800000, {"tetelrend": "MA-17-12-01"}),
                ("MA-17-13-01", "Energetikai tanúsítvány és használatbavétel (Energy certificate and occupation permit)", "klt", 1, 4200000, {"tetelrend": "MA-17-13-01"}),
                ("MA-17-14-01", "Takarítás és területrendezés átadás előtt (Final clean and site reinstatement)", "klt", 1, 5400000, {"tetelrend": "MA-17-14-01"}),
            ],
        ),
        (
            "MA-07",
            "07 - BELSŐÉPÍTÉSZETI MUNKÁK (Interior fit-out)",
            {"tetelrend": "MA-07"},
            [
                ("MA-07-11-01", "Konyhabútor alapkiépítés lakásonként (Base kitchen units per flat)", "db", 96, 985000, {"tetelrend": "MA-07-11-01"}),
                ("MA-07-12-01", "Beépített szekrény az előszobában (Fitted hallway wardrobe)", "db", 96, 425000, {"tetelrend": "MA-07-12-01"}),
                ("MA-07-13-01", "Fürdőszoba szaniter és csaptelep szerelvényezés (Bathroom sanitaryware and taps)", "db", 96, 385000, {"tetelrend": "MA-07-13-01"}),
                ("MA-07-14-01", "Postaláda szekrény és névtáblák a földszinten (Mailboxes and nameplates)", "db", 2, 1450000, {"tetelrend": "MA-07-14-01"}),
                ("MA-07-15-01", "Lépcsőházi burkolat és korlát (Stair core finishes and handrail)", "m2", 620, 24500, {"tetelrend": "MA-07-15-01"}),
                ("MA-07-16-01", "Belsőépítészeti világítás a közös terekben (Decorative lighting to common areas)", "db", 84, 68500, {"tetelrend": "MA-07-16-01"}),
                ("MA-07-17-01", "Üzlethelyiségek shell and core átadása (Retail units delivered shell and core)", "m2", 480, 42500, {"tetelrend": "MA-07-17-01"}),
                ("MA-07-18-01", "Tárolórekeszek a mélygarázsban (Storage cages in the car park)", "db", 96, 118000, {"tetelrend": "MA-07-18-01"}),
            ],
        ),
    ],
    markups=[
        ("Általános költség (General overhead)", 8.0, "overhead", "direct_cost"),
        ("Nyereség (Profit)", 6.0, "profit", "direct_cost"),
        ("Tartalék keret (Contingency)", 5.0, "contingency", "direct_cost"),
        ("ÁFA 27 százalék (VAT at 27 percent)", 27.0, "tax", "cumulative"),
    ],
    total_months=22,
    tender_name="Generálkivitelezői szerződés - Társasház, Budapest XIII.",
    tender_companies=[
        ("Duna-Parti Építő Zrt.", "tender@dunaparti.example", 0.98),
        ("Körvárosi Fővállalkozó Kft.", "ajanlat@korvarosi.example", 1.04),
        ("Pesti Magasépítő Zrt.", "beszerzes@pestimagas.example", 1.01),
    ],
    tender_packages=[
        (
            "Szerkezetépítés (Structural works)",
            "Földmunka, alapozás, monolit vasbeton szerkezet és falazatok.",
            "evaluating",
            [
                ("Duna-Parti Építő Zrt.", "tender@dunaparti.example", 0.98),
                ("Körvárosi Fővállalkozó Kft.", "ajanlat@korvarosi.example", 1.04),
                ("Pesti Magasépítő Zrt.", "beszerzes@pestimagas.example", 1.01),
            ],
        ),
        (
            "Épületgépészet és erősáram (Mechanical and electrical)",
            "Hőközpont, padlófűtés, szellőzés, erősáramú szerelés és felvonók.",
            "issued",
            [
                ("Termál Gépészet Kft.", "ajanlat@termalgep.example", 0.99),
                ("Villamos Rendszerek Zrt.", "tender@villrend.example", 1.03),
                ("Épületszerelő Csoport Kft.", "beszerzes@epuletszerelo.example", 1.02),
            ],
        ),
    ],
    project_metadata={
        "address": "Váci út 152, 1138 Budapest, Hungary",
        "client": "Váci Úti Lakóingatlan Fejlesztő Kft.",
        "architect": "Nyugati Tervezőiroda Kft.",
        "quantity_surveyor": "Költségvetés és Kivitelezés Tanácsadó Kft.",
        "structural_engineer": "Szerkezettervező Mérnökiroda Kft.",
        "gfa_m2": 11400,
        "site_area_m2": 4200,
        "storeys": 7,
        "basement_levels": 1,
        "flats": 96,
        "parking_spaces": 104,
        "construction_standards": [
            "253/1997. (XII. 20.) Korm. rendelet (OTÉK)",
            "7/2006. (V. 24.) TNM rendelet - energetikai követelmények",
            "54/2014. (XII. 5.) BM rendelet - Országos Tűzvédelmi Szabályzat",
            "191/2009. (IX. 15.) Korm. rendelet - építőipari kivitelezési tevékenység",
            "MSZ EN 1992 (Eurocode 2) - betonszerkezetek",
        ],
        "estimating_method": "Magasépítési ágazati tételrend, anyag és díj egységárral tételenként",
        "regulator": "Budapest Főváros XIII. kerületi Önkormányzat építéshatóság",
        "vat_note": (
            "Minden egységár nettó. Az általános 27 százalékos áfa a fedlapon, a tartalék keret "
            "után kerül felszámításra. Új lakóingatlan értékesítésére kedvezményes kulcs "
            "vonatkozhat, ez az építési költségvetést nem érinti."
        ),
        "contract": "Átalánydíjas generálkivitelezői szerződés",
        "currency_note": "A forintnak a gyakorlatban nincs váltópénze, ezért az egységárak egész számok.",
    },
)
