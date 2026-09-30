# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: hungary-hu - Irodaház, Debrecen
# ---------------------------------------------------------------------------
# The second Hungarian demo, and deliberately a different kind of job from the
# Budapest residential block: a speculative office building outside the capital,
# where the fit-out is shell-and-core and the mechanical chapter carries the
# weight the residential bill puts into the flats.
#
# Same item order, same nine-column code, same two unit prices per line. What
# changes is which chapters are heavy, which is the point of shipping two: a
# reader comparing them can see that the chapter numbers are the item order's
# and not a per-project invention.
#
# Prices are Debrecen 2026 levels in HUF, net of VAT. Regional prices outside
# Budapest run lower on labour and about level on material, which is visible in
# the rates below and is the usual reason a Hungarian estimator asks where the
# job is before quoting anything.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-debrecen",
    project_name="Irodaház - Debrecen, Északnyugati Ipari Park (Office Building, Debrecen)",
    project_description=(
        "Új építésű, spekulatív irodaház a debreceni Északnyugati Ipari Park "
        "területén: földszint plusz négy emelet, mintegy 8 200 m2 bruttó "
        "szintterülettel, shell and core kialakításban, bérlői beépítés nélkül. "
        "Monolit vasbeton pillérvázas szerkezet, üvegezett függönyfal, "
        "gépészeti központ a tetőn. BREEAM Very Good célkitűzés. "
        "New-build speculative office building in the North-West Industrial "
        "Park in Debrecen: ground plus four storeys, approx. 8,200 m2 gross, "
        "delivered shell and core with no tenant fit-out. Reinforced concrete "
        "column frame, glazed curtain wall, roof-mounted plant. Targeting "
        "BREEAM Very Good. Priced at Debrecen 2026 levels in forint, net of "
        "VAT."
    ),
    region="HU",
    classification_standard="tetelrend",
    currency="HUF",
    locale="hu",
    address={
        "street": "Északnyugati Ipari Park, Vezér utca 12",
        "city": "Debrecen",
        "postcode": "4031",
        "country": "Hungary",
        "lat": 47.5566,
        "lng": 21.5910,
    },
    # ``hungary``, not ``tetelrend``: the latter is the classification
    # standard set above, and naming it here asked the engine for a rule
    # set that does not exist. The engine logs that and carries on, so
    # both Hungarian demos ran the generic quality rules and none of the
    # country's own. The pack manifest had it right all along.
    validation_rule_sets=["hungary", "boq_quality", "project_completeness"],
    boq_name="Költségvetés - irodaház, shell and core (Bill of Quantities)",
    boq_description=(
        "Fejezetenkénti költségvetés a magasépítési ágazati tételrend szerint, "
        "shell and core tartalommal: a bérlői beépítés nem része a "
        "költségvetésnek. Debrecen 2026-os árszint, nettó forintban. "
        "Chapter-by-chapter bill to the building sectoral item order, shell and "
        "core scope, tenant fit-out excluded."
    ),
    boq_metadata={
        "standard": "Magasépítési ágazati tételrend (MA-CC-SSS)",
        "phase": "Kiviteli terv - tenderköltségvetés (Tender bill on construction drawings)",
        "base_date": "2026-Q1",
        "price_level": "Debrecen 2026 (HUF, nettó)",
    },
    sections=[
        (
            "MA-01",
            "01 - ÁLTALÁNOS, JÁRULÉKOS KÖLTSÉGEK (General and ancillary costs)",
            {"tetelrend": "MA-01"},
            [
                ("MA-01-11-01", "Felvonulási létesítmények (Site accommodation)", "hó", 16, 620000, {"tetelrend": "MA-01-11-01"}),
                ("MA-01-12-01", "Építési terület kerítése (Site hoarding)", "m", 420, 28500, {"tetelrend": "MA-01-12-01"}),
                ("MA-01-13-01", "Toronydaru bérlet és telepítés (Tower crane hire and erection)", "hó", 12, 2180000, {"tetelrend": "MA-01-13-01"}),
                ("MA-01-14-01", "Munkavédelmi koordináció (Site safety coordination)", "klt", 1, 9800000, {"tetelrend": "MA-01-14-01"}),
                ("MA-01-16-01", "Felelős műszaki vezetés (Responsible technical management)", "hó", 16, 820000, {"tetelrend": "MA-01-16-01"}),
                ("MA-01-17-01", "Biztosítás és teljesítési garancia (Insurance and performance bond)", "klt", 1, 14500000, {"tetelrend": "MA-01-17-01"}),
            ],
        ),
        (
            "MA-02",
            "02 - ELŐKÉSZÍTŐ MUNKÁK (Preparatory works)",
            {"tetelrend": "MA-02"},
            [
                ("MA-02-11-01", "Terület tisztítása, humuszleszedés (Site clearance and topsoil strip)", "m2", 9800, 1450, {"tetelrend": "MA-02-11-01"}),
                ("MA-02-14-01", "Geodéziai kitűzés (Setting out)", "klt", 1, 2900000, {"tetelrend": "MA-02-14-01"}),
                ("MA-02-16-01", "Ipari parki közmű csatlakozás előkészítése (Industrial park utility connection works)", "klt", 1, 11500000, {"tetelrend": "MA-02-16-01"}),
            ],
        ),
        (
            "MA-03",
            "03 - FÖLDMUNKA, ALAPOZÁS (Earthworks and foundations)",
            {"tetelrend": "MA-03"},
            [
                ("MA-03-11-01", "Munkagödör kiemelése géppel (Bulk excavation, machine)", "m3", 8400, 3950, {"tetelrend": "MA-03-11-01"}),
                ("MA-03-12-01", "CFA cölöpalapozás, 60 cm átmérő (CFA piling, 600 mm diameter)", "m", 2350, 34500, {"tetelrend": "MA-03-12-01"}),
                ("MA-03-13-01", "Szerelőbeton C12/15 (Blinding concrete C12/15)", "m3", 165, 42500, {"tetelrend": "MA-03-13-01"}),
                ("MA-03-13-02", "Cölöpösszefogó gerenda és talpgerenda C30/37 (Pile caps and ground beams C30/37)", "m3", 620, 74500, {"tetelrend": "MA-03-13-02"}),
                ("MA-03-13-03", "Betonacél B500B alapozásban (Reinforcement B500B in foundations)", "t", 96, 442000, {"tetelrend": "MA-03-13-03"}),
                ("MA-03-14-01", "Talajnedvesség elleni szigetelés (Damp-proofing to substructure)", "m2", 1980, 8200, {"tetelrend": "MA-03-14-01"}),
                ("MA-03-15-01", "Visszatöltés tömörítéssel (Backfill compacted)", "m3", 3200, 4600, {"tetelrend": "MA-03-15-01"}),
            ],
        ),
        (
            "MA-04",
            "04 - SZERKEZETÉPÍTÉSI MUNKÁK (Structural works)",
            {"tetelrend": "MA-04"},
            [
                ("MA-04-11-01", "Monolit vasbeton pillér C30/37 (Cast in-situ RC column C30/37)", "m3", 540, 89500, {"tetelrend": "MA-04-11-01"}),
                ("MA-04-11-02", "Monolit vasbeton merevítő mag C30/37 (RC core wall C30/37)", "m3", 780, 82500, {"tetelrend": "MA-04-11-02"}),
                ("MA-04-12-01", "Monolit vasbeton födém C30/37, 26 cm (Cast in-situ RC slab, 260 mm)", "m2", 8200, 38500, {"tetelrend": "MA-04-12-01"}),
                ("MA-04-13-01", "Betonacél B500B felmenő szerkezetben (Reinforcement B500B in superstructure)", "t", 496, 452000, {"tetelrend": "MA-04-13-01"}),
                ("MA-04-14-01", "Rendszerzsaluzás pillérekhez és falakhoz (System formwork to columns and walls)", "m2", 7400, 6400, {"tetelrend": "MA-04-14-01"}),
                ("MA-04-14-02", "Födémzsaluzás alátámasztással (Slab formwork with propping)", "m2", 8600, 6900, {"tetelrend": "MA-04-14-02"}),
                ("MA-04-16-01", "Acél tetőszerkezet a gépészeti központhoz (Steel roof frame to plant enclosure)", "t", 42, 985000, {"tetelrend": "MA-04-16-01"}),
            ],
        ),
        (
            "MA-05",
            "05 - KÜLSŐ SZAKIPARI MUNKÁK, ÉPÜLET ZÁRÁS (Envelope and external trades)",
            {"tetelrend": "MA-05"},
            [
                ("MA-05-12-01", "Alumínium függönyfal háromrétegű üvegezéssel (Aluminium curtain wall, triple glazed)", "m2", 3400, 268000, {"tetelrend": "MA-05-12-01"}),
                ("MA-05-12-02", "Nyitható szellőzőszárnyak a függönyfalban (Openable vents within curtain wall)", "db", 96, 385000, {"tetelrend": "MA-05-12-02"}),
                ("MA-05-11-01", "Szendvicspanel homlokzat a technikai szinten (Sandwich panel cladding at plant level)", "m2", 620, 42500, {"tetelrend": "MA-05-11-01"}),
                ("MA-05-13-01", "Lapostető rétegrend PVC vízszigeteléssel (Flat roof build-up, PVC membrane)", "m2", 2050, 34500, {"tetelrend": "MA-05-13-01"}),
                ("MA-05-14-01", "Külső árnyékolás, fix lamellák déli homlokzaton (External fixed brise-soleil, south facade)", "m2", 480, 96500, {"tetelrend": "MA-05-14-01"}),
                ("MA-05-15-01", "Bádogos szerkezetek és attika lefedés (Sheet metal flashings and parapet capping)", "m", 640, 13800, {"tetelrend": "MA-05-15-01"}),
            ],
        ),
        (
            "MA-06",
            "06 - ÉPÍTÉSZETI, SZAKIPARI MUNKÁK (Architectural and finishing trades)",
            {"tetelrend": "MA-06"},
            [
                ("MA-06-11-01", "Belső vakolat a magterekben (Internal plaster to core areas)", "m2", 4800, 4400, {"tetelrend": "MA-06-11-01"}),
                ("MA-06-12-01", "Aljzatbeton simított felülettel (Power-floated screed to office floors)", "m2", 7800, 8900, {"tetelrend": "MA-06-12-01"}),
                ("MA-06-13-01", "Kerámia burkolat mosdókban (Ceramic tiling to washrooms)", "m2", 780, 20500, {"tetelrend": "MA-06-13-01"}),
                ("MA-06-14-01", "Tűzgátló ajtó a lépcsőházakban (Fire door to stair cores)", "db", 42, 285000, {"tetelrend": "MA-06-14-01"}),
                ("MA-06-15-01", "Gipszkarton válaszfal a magterekben (Plasterboard partition to cores)", "m2", 1650, 13400, {"tetelrend": "MA-06-15-01"}),
                ("MA-06-11-02", "Festés a közös terekben (Painting to common areas)", "m2", 6200, 2950, {"tetelrend": "MA-06-11-02"}),
            ],
        ),
        (
            "MA-09",
            "09 - ÉPÜLETGÉPÉSZET (Mechanical services)",
            {"tetelrend": "MA-09"},
            [
                ("MA-09-11-01", "Levegő-víz hőszivattyús hőtermelő központ (Air-to-water heat pump plant)", "klt", 1, 128000000, {"tetelrend": "MA-09-11-01"}),
                ("MA-09-14-01", "Központi légkezelő hővisszanyeréssel (Central AHU with heat recovery)", "db", 3, 24500000, {"tetelrend": "MA-09-14-01"}),
                ("MA-09-14-02", "Légcsatorna hálózat, horganyzott (Galvanised ductwork distribution)", "m2", 4200, 28500, {"tetelrend": "MA-09-14-02"}),
                ("MA-09-14-03", "Fan-coil egységek az irodaszinteken (Fan coil units to office floors)", "db", 96, 685000, {"tetelrend": "MA-09-14-03"}),
                ("MA-09-12-01", "Vízellátás alapvezeték és felszálló (Water supply mains and risers)", "m", 860, 22500, {"tetelrend": "MA-09-12-01"}),
                ("MA-09-13-01", "Szaniter szerelvények mosdóblokkonként (Sanitaryware per washroom block)", "db", 10, 3850000, {"tetelrend": "MA-09-13-01"}),
            ],
        ),
        (
            "MA-10",
            "10 - TŰZVÉDELMI RENDSZEREK, OLTÓRENDSZER (Fire protection and suppression)",
            {"tetelrend": "MA-10"},
            [
                ("MA-10-11-01", "Sprinkler rendszer az irodaszinteken (Sprinkler installation to office floors)", "m2", 8200, 9800, {"tetelrend": "MA-10-11-01"}),
                ("MA-10-11-02", "Sprinkler szivattyúház és tartály (Sprinkler pump house and tank)", "klt", 1, 42500000, {"tetelrend": "MA-10-11-02"}),
                ("MA-10-12-01", "Tűzjelző rendszer, címezhető (Addressable fire alarm system)", "m2", 8200, 4200, {"tetelrend": "MA-10-12-01"}),
                ("MA-10-13-01", "Füstelvezetés a lépcsőházakban (Stair core smoke control)", "klt", 1, 18500000, {"tetelrend": "MA-10-13-01"}),
            ],
        ),
        (
            "MA-11",
            "11 - ERŐSÁRAMÚ MUNKÁK (Electrical power)",
            {"tetelrend": "MA-11"},
            [
                ("MA-11-11-01", "Transzformátor állomás és fő elosztó (Substation and main switchboard)", "klt", 1, 68500000, {"tetelrend": "MA-11-11-01"}),
                ("MA-11-12-01", "Kábeltálcás gerinchálózat emeletenként (Busbar and tray distribution per floor)", "db", 5, 8900000, {"tetelrend": "MA-11-12-01"}),
                ("MA-11-13-01", "LED világítás a közös terekben és irodákban (LED lighting, common areas and shell offices)", "m2", 8200, 12400, {"tetelrend": "MA-11-13-01"}),
                ("MA-11-14-01", "Villámvédelem és földelés (Lightning protection and earthing)", "klt", 1, 14800000, {"tetelrend": "MA-11-14-01"}),
                ("MA-11-15-01", "Tetőre telepített napelemes rendszer, 180 kWp (Roof-mounted PV, 180 kWp)", "kWp", 180, 285000, {"tetelrend": "MA-11-15-01"}),
            ],
        ),
        (
            "MA-13",
            "13 - AUTOMATIKA (Building automation)",
            {"tetelrend": "MA-13"},
            [
                ("MA-13-11-01", "Épületfelügyeleti rendszer, BMS központ (Building management system head end)", "klt", 1, 34500000, {"tetelrend": "MA-13-11-01"}),
                ("MA-13-12-01", "Mezőszintű szabályozás és mérés (Field-level control and metering)", "db", 620, 68500, {"tetelrend": "MA-13-12-01"}),
                ("MA-13-13-01", "Energiamonitoring a BREEAM követelményhez (Energy monitoring for BREEAM credit)", "klt", 1, 9800000, {"tetelrend": "MA-13-13-01"}),
            ],
        ),
        (
            "MA-15",
            "15 - FELVONÓK, EMELŐSZERKEZETEK (Lifts and lifting equipment)",
            {"tetelrend": "MA-15"},
            [
                ("MA-15-11-01", "Személyfelvonó 13 személyes, 5 megálló (Passenger lift, 13 person, 5 stops)", "db", 2, 32500000, {"tetelrend": "MA-15-11-01"}),
                ("MA-15-12-01", "Üzembe helyezés és hatósági engedélyezés (Commissioning and statutory approval)", "klt", 1, 3800000, {"tetelrend": "MA-15-12-01"}),
            ],
        ),
        (
            "MA-16",
            "16 - KÜLSŐ MUNKÁK (External works)",
            {"tetelrend": "MA-16"},
            [
                ("MA-16-11-01", "Aszfaltburkolatú parkoló és út (Asphalt car park and access road)", "m2", 4800, 14800, {"tetelrend": "MA-16-11-01"}),
                ("MA-16-12-01", "Kertépítés és fásítás (Landscaping and tree planting)", "m2", 2400, 11500, {"tetelrend": "MA-16-12-01"}),
                ("MA-16-13-01", "Csapadékvíz elszikkasztás és tározó (Surface water attenuation and soakaway)", "klt", 1, 22500000, {"tetelrend": "MA-16-13-01"}),
                ("MA-16-15-01", "Kerítés, sorompó és beléptetés (Fence, barrier and access control)", "klt", 1, 16800000, {"tetelrend": "MA-16-15-01"}),
            ],
        ),
        (
            "MA-17",
            "17 - ÁTADÁS (Handover)",
            {"tetelrend": "MA-17"},
            [
                ("MA-17-11-01", "Beszabályozás, próbaüzem, integrált próbák (Commissioning and integrated testing)", "klt", 1, 18500000, {"tetelrend": "MA-17-11-01"}),
                ("MA-17-12-01", "Megvalósulási dokumentáció (As-built documentation)", "klt", 1, 5800000, {"tetelrend": "MA-17-12-01"}),
                ("MA-17-13-01", "Energetikai tanúsítvány és BREEAM minősítés (Energy certificate and BREEAM assessment)", "klt", 1, 12400000, {"tetelrend": "MA-17-13-01"}),
                ("MA-17-14-01", "Átadási takarítás (Handover clean)", "klt", 1, 3900000, {"tetelrend": "MA-17-14-01"}),
            ],
        ),
        (
            "MA-07",
            "07 - BELSŐÉPÍTÉSZETI MUNKÁK (Interior fit-out, common areas only)",
            {"tetelrend": "MA-07"},
            [
                ("MA-07-11-01", "Recepciópult és fogadótér burkolatai (Reception desk and lobby finishes)", "klt", 1, 24500000, {"tetelrend": "MA-07-11-01"}),
                ("MA-07-12-01", "Mosdóblokkok belsőépítészeti kialakítása (Washroom fit-out)", "db", 10, 4850000, {"tetelrend": "MA-07-12-01"}),
                ("MA-07-13-01", "Teakonyhák szintenként (Tea points per floor)", "db", 5, 3400000, {"tetelrend": "MA-07-13-01"}),
                ("MA-07-14-01", "Lépcsőházi burkolat és korlát (Stair core finishes and balustrade)", "m2", 480, 26500, {"tetelrend": "MA-07-14-01"}),
                ("MA-07-15-01", "Bérlői elválasztó falak előkészítése (Provision for tenant demising walls)", "m", 320, 42500, {"tetelrend": "MA-07-15-01"}),
                ("MA-07-16-01", "Belsőépítészeti világítás a fogadótérben (Feature lighting to reception)", "db", 48, 96500, {"tetelrend": "MA-07-16-01"}),
                ("MA-07-17-01", "Feliratozás és tájékoztató rendszer (Signage and wayfinding)", "klt", 1, 8900000, {"tetelrend": "MA-07-17-01"}),
                ("MA-07-18-01", "Takarítószer tároló és karbantartói helyiség (Cleaner store and maintenance room)", "db", 5, 1450000, {"tetelrend": "MA-07-18-01"}),
                ("MA-07-19-01", "Kerékpártároló és zuhanyzó a földszinten (Cycle store and shower at ground level)", "klt", 1, 6800000, {"tetelrend": "MA-07-19-01"}),
            ],
        ),
        (
            "MA-12",
            "12 - GYENGEÁRAMÚ MUNKÁK (Extra-low voltage and communications)",
            {"tetelrend": "MA-12"},
            [
                ("MA-12-11-01", "Strukturált kábelhálózat gerinc és szintenkénti elosztás (Structured cabling, backbone and floor distribution)", "m2", 8200, 5400, {"tetelrend": "MA-12-11-01"}),
                ("MA-12-11-02", "Szerverszoba és rendezőszekrények (Comms room and cabinets)", "klt", 1, 18500000, {"tetelrend": "MA-12-11-02"}),
                ("MA-12-12-01", "Beléptető rendszer a főbejáraton és szintenként (Access control, entrance and floors)", "db", 42, 385000, {"tetelrend": "MA-12-12-01"}),
                ("MA-12-12-02", "Videómegfigyelő rendszer kamerákkal (CCTV system with cameras)", "db", 68, 268000, {"tetelrend": "MA-12-12-02"}),
                ("MA-12-13-01", "Behatolásjelző rendszer (Intruder alarm system)", "klt", 1, 9800000, {"tetelrend": "MA-12-13-01"}),
                ("MA-12-14-01", "Audiovizuális előkészítés a tárgyalókhoz (AV provision to meeting rooms)", "klt", 1, 12400000, {"tetelrend": "MA-12-14-01"}),
                ("MA-12-15-01", "Mobil jelerősítő rendszer a magterekben (In-building mobile coverage)", "klt", 1, 14800000, {"tetelrend": "MA-12-15-01"}),
                ("MA-12-16-01", "Parkolóhely érzékelés és kijelzés (Car park occupancy detection and display)", "db", 156, 68500, {"tetelrend": "MA-12-16-01"}),
                ("MA-12-17-01", "Óra és hangosítás a közös terekben (Clock and public address to common areas)", "klt", 1, 6400000, {"tetelrend": "MA-12-17-01"}),
            ],
        ),
    ],
    markups=[
        ("Általános költség (General overhead)", 7.5, "overhead", "direct_cost"),
        ("Nyereség (Profit)", 6.5, "profit", "direct_cost"),
        ("Tartalék keret (Contingency)", 4.0, "contingency", "direct_cost"),
        ("ÁFA 27 százalék (VAT at 27 percent)", 27.0, "tax", "cumulative"),
    ],
    total_months=16,
    tender_name="Generálkivitelezői szerződés - Irodaház, Debrecen",
    tender_companies=[
        ("Tiszántúli Építő Zrt.", "tender@tiszantuli.example", 0.97),
        ("Hajdúsági Fővállalkozó Kft.", "ajanlat@hajdusagi.example", 1.02),
        ("Alföldi Magasépítő Zrt.", "beszerzes@alfoldimagas.example", 1.05),
    ],
    tender_packages=[
        (
            "Szerkezet és homlokzat (Structure and envelope)",
            "Cölöpalapozás, monolit vasbeton váz, függönyfal és tetőszerkezet.",
            "evaluating",
            [
                ("Tiszántúli Építő Zrt.", "tender@tiszantuli.example", 0.97),
                ("Hajdúsági Fővállalkozó Kft.", "ajanlat@hajdusagi.example", 1.02),
                ("Alföldi Magasépítő Zrt.", "beszerzes@alfoldimagas.example", 1.05),
            ],
        ),
        (
            "Gépészet, erősáram, automatika (MEP and controls)",
            "Hőszivattyús központ, légkezelés, sprinkler, erősáram, BMS és napelemes rendszer.",
            "draft",
            [
                ("Keleti Gépészeti Kft.", "ajanlat@keletigep.example", 1.00),
                ("Debreceni Villanyszerelő Zrt.", "tender@debvill.example", 1.03),
                ("Automatika és Energia Kft.", "beszerzes@autoenergia.example", 0.98),
            ],
        ),
    ],
    project_metadata={
        "address": "Északnyugati Ipari Park, Vezér utca 12, 4031 Debrecen, Hungary",
        "client": "Debreceni Irodafejlesztő Kft.",
        "architect": "Keleti Építész Stúdió Kft.",
        "quantity_surveyor": "Költségvetés és Kivitelezés Tanácsadó Kft.",
        "structural_engineer": "Alföldi Szerkezettervező Kft.",
        "gfa_m2": 8200,
        "site_area_m2": 9800,
        "storeys": 5,
        "basement_levels": 0,
        "parking_spaces": 156,
        "delivery_standard": "Shell and core; a bérlői beépítés nem része a költségvetésnek",
        "construction_standards": [
            "253/1997. (XII. 20.) Korm. rendelet (OTÉK)",
            "7/2006. (V. 24.) TNM rendelet - energetikai követelmények",
            "54/2014. (XII. 5.) BM rendelet - Országos Tűzvédelmi Szabályzat",
            "MSZ EN 1993 (Eurocode 3) - acélszerkezetek",
            "BREEAM International New Construction",
        ],
        "estimating_method": "Magasépítési ágazati tételrend, anyag és díj egységárral tételenként",
        "regulator": "Debrecen Megyei Jogú Város építéshatóság",
        "vat_note": "Minden egységár nettó. Az általános 27 százalékos áfa a fedlapon kerül felszámításra.",
        "contract": "Átalánydíjas generálkivitelezői szerződés",
        "regional_price_note": (
            "A debreceni árszint a budapestinél alacsonyabb munkadíjat és nagyjából azonos "
            "anyagárat jelent, ezért kérdezi meg a költségvető először, hogy hol van a munka."
        ),
    },
)
