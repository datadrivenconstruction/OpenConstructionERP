# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Demo pack: Budynek mieszkalny wielorodzinny, Warszawa-Wola
# ---------------------------------------------------------------------------
# A Polish kosztorys is built from nakłady rzeczowe: each position names a
# catalogue table (the podstawa column) and the estimator prices the labour,
# material and plant that table holds. The catalogues are the KNR family,
# katalogi nakładów rzeczowych, and a reference reads KNR 2-02 0201-01, which
# is the catalogue, the table and the variant within the table. Every line
# below carries one under the "knr" key.
#
# WHY EVERY LINE ALSO CARRIES A DIN 276 GROUP. A Warsaw estimator works in
# działy of a kosztorys and in KNR positions, and every line below carries its
# KNR reference under "knr", which the "poland" rule set checks. The registry
# has no Polish cost-group hierarchy and stores a Polish project under DIN 276,
# its nearest one, so the project runs the DIN 276 cost-group rule too. The
# bill used to carry no DIN 276 group at all, and the Validate button failed
# every line for it. Each dział now maps onto the DIN 276 group it falls in,
# the same dual coding the Nordic and Alpine demos carry.

# WHAT IS INDICATIVE HERE, PLAINLY. The KNR catalogue numbers are right: 2-01
# for earthworks, 2-02 for building structures and finishes, 2-15 for sanitary
# and heating, 2-17 for ventilation, 2-18 for external mains, 2-21 for
# landscaping, 2-31 for paving, 0-33 for the external render system and 5-08
# for electrical work. The four-digit table numbers and the two-digit variants
# after the hyphen are shaped rather than verified against the published
# catalogue text, so treat them as pointing at the right chapter and not at a
# specific published norm. Weaker still are the modern-technology lines, where
# a Polish estimator would reach for a specialist catalogue or price the item
# by kalkulacja indywidualna instead of a KNR position: the lifts (8.8), the
# ELV package (8.7), the ventilated rainscreen (5.2), the plasterboard work
# (4.3, 4.5, 4.7) and the photovoltaic array (8.11). The references on those
# are placeholders of the right shape and nothing more. Replace all of them
# from a current catalogue before the bill is used for anything but a demo.
#
# The units are the ones a kosztorys writes: m, m2, m3 and t alongside szt for
# counted items, kpl for a complete installation and mies for the time-related
# site costs. Twelve lines carry a single kpl and those are the coarsest in the
# bill: a real document would put a kalkulacja indywidualna behind each of them
# with its own priced breakdown rather than one komplet rate. They are the
# systems that get bought as a package anyway, the heat substation, the
# ventilation, the ELV works and the photovoltaic array, so a lump entry is the
# right shape for a demo and the wrong shape for a tender.
#
# Rates are Warsaw 2026 levels in PLN, net of VAT, and are direct cost
# (koszt bezpośredni R + M + S) with the narzuty taken as separate markup
# lines. They are market estimates rather than a priced norm base: right order
# of magnitude and right relative to their neighbours, not sourced from a
# published bulletin. The quantities follow the building described below and
# were derived from it, so they hang together, but they are not a przedmiar
# taken off drawings.
#
# One structural limitation of the format. A Polish kosztorys szczegółowy
# carries the R, M and S split on every position and norms koszty pośrednie on
# R + S rather than on the whole direct cost. DemoTemplate has one rate per
# line and its markups apply to either the direct cost or the running total, so
# the percentages below are equivalents against direct cost. The money lands in
# the right place, the sensitivity to the labour and plant share does not
# survive; project_metadata["markup_base_note"] says so in full.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-warsaw",
    project_name="Budynek mieszkalny wielorodzinny - Warszawa, Wola (Residential Building, Warsaw)",
    project_description=(
        "Budowa budynku mieszkalnego wielorodzinnego w dzielnicy Wola w Warszawie: "
        "dwie klatki schodowe, osiem kondygnacji nadziemnych i jedna podziemna, "
        "128 mieszkań, garaż podziemny na 96 stanowisk oraz dwa lokale usługowe "
        "w parterze. Konstrukcja monolityczna żelbetowa na płycie fundamentowej, "
        "ściany wypełniające z bloczków silikatowych, dach płaski, elewacja w "
        "systemie bezspoinowego ocieplenia z akcentami z płyt włóknocementowych. "
        "Powierzchnia całkowita około 14 800 m2, powierzchnia użytkowa mieszkań "
        "około 8 900 m2, działka 5 400 m2. Mieszkania przekazywane w standardzie "
        "deweloperskim. Budynek średniowysoki, kategoria zagrożenia ludzi ZL IV, "
        "klasa odporności pożarowej B, spełnia wymagania Warunków Technicznych "
        "obowiązujących od 31 grudnia 2020 r. Kosztorys inwestorski sporządzony "
        "metodą kalkulacji szczegółowej na podstawie katalogów KNR, poziom cen "
        "Warszawa 2026, wartość robót budowlanych netto około 65 mln zł. "
        "New-build residential block in the Wola district of Warsaw: two stair "
        "cores, eight storeys above grade and one basement level, 128 flats, an "
        "underground car park with 96 spaces and two ground-floor retail units. "
        "Cast in-situ reinforced concrete frame on a raft foundation, sand-lime "
        "block infill walls, flat roof, external wall insulation with "
        "fibre-cement rainscreen accents. Gross area approx. 14,800 m2, net "
        "saleable flat area approx. 8,900 m2, site 5,400 m2. Flats handed over "
        "to Polish developer standard, that is plastered and screeded with "
        "services capped off. Priced at Warsaw 2026 levels, net of VAT, "
        "approx. PLN 65 million for the building works."
    ),
    region="PL",
    classification_standard="din276",
    currency="PLN",
    locale="pl",
    project_code="WAW-WOL-2026-01",
    address={
        "street": "ulica Marcina Kasprzaka 29",
        "city": "Warszawa",
        "postcode": "01-234",
        "country": "Poland",
        "lat": 52.2296,
        "lng": 20.9603,
    },
    validation_rule_sets=["poland", "boq_quality", "project_completeness"],
    boq_name="Kosztorys inwestorski - roboty budowlane i instalacyjne (Investor's cost estimate)",
    boq_description=(
        "Kosztorys inwestorski w układzie działów robót, sporządzony metodą kalkulacji "
        "szczegółowej. Podstawą nakładów rzeczowych są katalogi KNR, ceny jednostkowe "
        "czynników produkcji przyjęto na poziomie rynku warszawskiego 2026 r. Wartości "
        "pozycji są kosztem bezpośrednim (robocizna, materiały, sprzęt); koszty pośrednie, "
        "zysk i podatek VAT doliczono w narzutach. Investor's cost estimate arranged by "
        "trade section, detailed calculation method, resource inputs from the KNR "
        "catalogues. Position values are direct cost; indirect costs, profit and VAT are "
        "added as markup lines."
    ),
    boq_metadata={
        "standard": "Rozporządzenie MRiT z 20.12.2021 (Dz.U. 2021 poz. 2458); nakłady rzeczowe wg katalogów KNR",
        "phase": "Projekt wykonawczy - kosztorys inwestorski (Detailed design, investor's estimate)",
        "base_date": "2026-Q1",
        "price_level": "Warszawa 2026, ceny netto (Warsaw 2026, net of VAT)",
        "pricing_method": "Kalkulacja szczegółowa R + M + S z narzutami Kp i Z (detailed R + M + S calculation)",
    },
    sections=[
        (
            "01",
            "Dział 1. Roboty przygotowawcze i ziemne (Site preparation and earthworks)",
            {"knr": "KNR 2-01", "din276": "310"},
            [
                ("1.1", "Zagospodarowanie placu budowy, ogrodzenie tymczasowe, zaplecze i drogi montażowe (Site setup, hoarding, accommodation and haul roads)", "kpl", 1.0, 420_000.0, {"knr": "KNR 2-01 0101-01", "din276": "310"}),
                ("1.2", "Usunięcie warstwy humusu grubości 20 cm spycharką (Topsoil strip, 20 cm, dozer)", "m3", 1_080.0, 38.0, {"knr": "KNR 2-01 0126-02", "din276": "310"}),
                ("1.3", "Wykopy szerokoprzestrzenne pod kondygnację podziemną koparką podsiębierną (Bulk excavation for basement, backacter)", "m3", 16_800.0, 32.0, {"knr": "KNR 2-01 0206-04", "din276": "310"}),
                ("1.4", "Obudowa wykopu z palisady z pali CFA fi 600 mm z oczepem żelbetowym (Excavation support, CFA pile palisade 600 mm with RC capping beam)", "m2", 1_210.0, 690.0, {"knr": "KNR 2-01 0301-05", "din276": "310"}),
                ("1.5", "Odwodnienie wykopu igłofiltrami z pompowaniem i zrzutem (Wellpoint dewatering of excavation, pumping and discharge)", "mies", 6.0, 48_000.0, {"knr": "KNR 2-01 0234-01", "din276": "310"}),
                ("1.6", "Zasypanie wykopów gruntem rodzimym z zagęszczeniem warstwami (Backfilling with site-won soil in compacted layers)", "m3", 4_200.0, 46.0, {"knr": "KNR 2-01 0230-02", "din276": "310"}),
                ("1.7", "Wywóz urobku samochodami samowyładowczymi do 15 km z utylizacją (Spoil haulage up to 15 km and disposal)", "m3", 13_500.0, 42.0, {"knr": "KNR 2-01 0214-03", "din276": "310"}),
                ("1.8", "Roboty ziemne ręczne w miejscach kolizji z uzbrojeniem i pod przyłącza (Hand excavation at service crossings and connection trenches)", "m3", 620.0, 145.0, {"knr": "KNR 2-01 0202-02", "din276": "310"}),
                ("1.9", "Myjka kół pojazdów na wyjeździe z budowy i oczyszczanie ulicy (Wheel wash at the site exit and street cleaning)", "mies", 20.0, 14_500.0, {"knr": "KNR 2-01 0101-04", "din276": "310"}),
            ],
        ),
        (
            "02",
            "Dział 2. Fundamenty i kondygnacja podziemna (Foundations and substructure)",
            {"knr": "KNR 2-02", "din276": "320"},
            [
                ("2.1", "Podkład z betonu niekonstrukcyjnego C8/10 grubości 10 cm pod płytę fundamentową (Blinding concrete C8/10, 10 cm, under raft)", "m3", 300.0, 480.0, {"knr": "KNR 2-02 0201-01", "din276": "320"}),
                ("2.2", "Płyta fundamentowa żelbetowa C30/37 W8 grubości 60 cm, beton z pompowaniem (Raft foundation C30/37 W8, 60 cm, pumped concrete)", "m3", 1_740.0, 640.0, {"knr": "KNR 2-02 0204-02", "din276": "320"}),
                ("2.3", "Ściany i słupy żelbetowe kondygnacji podziemnej C30/37 W8, beton (Basement RC walls and columns C30/37 W8, concrete)", "m3", 590.0, 790.0, {"knr": "KNR 2-02 0206-03", "din276": "320"}),
                ("2.4", "Strop nad kondygnacją podziemną C30/37 grubości 25 cm, beton (Slab over basement C30/37, 25 cm, concrete)", "m3", 725.0, 700.0, {"knr": "KNR 2-02 0212-02", "din276": "320"}),
                ("2.5", "Zbrojenie konstrukcji podziemnych stalą B500SP, przygotowanie i montaż (Reinforcement B500SP to substructure, cut, bend and fix)", "t", 372.0, 5_600.0, {"knr": "KNR 2-02 0290-02", "din276": "320"}),
                ("2.6", "Deskowanie systemowe ścian, słupów i stropu kondygnacji podziemnej (System formwork to basement walls, columns and slab)", "m2", 6_850.0, 82.0, {"knr": "KNR 2-02 0207-01", "din276": "320"}),
                ("2.7", "Izolacja przeciwwodna płyty i ścian fundamentowych z papy termozgrzewalnej w dwóch warstwach (Two-layer torched membrane tanking to raft and basement walls)", "m2", 3_850.0, 92.0, {"knr": "KNR 2-02 0603-04", "din276": "320"}),
                ("2.8", "Drenaż opaskowy z rur PVC fi 160 mm ze studniami rewizyjnymi (Perimeter drainage, PVC 160 mm, with inspection chambers)", "m", 240.0, 320.0, {"knr": "KNR 2-18 0801-02", "din276": "320"}),
                ("2.9", "Izolacja termiczna ścian fundamentowych z polistyrenu ekstrudowanego 12 cm (XPS insulation to basement walls, 120 mm)", "m2", 1_180.0, 118.0, {"knr": "KNR 0-33 0201-03", "din276": "320"}),
                ("2.10", "Ławy i stopy fundamentowe pod ściany oporowe rampy zjazdowej (Strip and pad footings to the ramp retaining walls)", "m3", 145.0, 890.0, {"knr": "KNR 2-02 0202-04", "din276": "320"}),
            ],
        ),
        (
            "03",
            "Dział 3. Konstrukcja żelbetowa nadziemia (Cast in-situ superstructure)",
            {"knr": "KNR 2-02", "din276": "350"},
            [
                ("3.1", "Ściany żelbetowe monolityczne C30/37 grubości 20-25 cm, beton z pompowaniem (Cast in-situ RC walls C30/37, 20-25 cm, pumped concrete)", "m3", 2_050.0, 730.0, {"knr": "KNR 2-02 0206-05", "din276": "350"}),
                ("3.2", "Słupy i podciągi żelbetowe C30/37 (RC columns and downstand beams C30/37)", "m3", 345.0, 820.0, {"knr": "KNR 2-02 0208-02", "din276": "350"}),
                ("3.3", "Stropy żelbetowe monolityczne C30/37 grubości 22 cm (Cast in-situ RC slabs C30/37, 22 cm)", "m3", 2_640.0, 700.0, {"knr": "KNR 2-02 0212-04", "din276": "350"}),
                ("3.4", "Biegi i spoczniki klatek schodowych żelbetowe monolityczne (Cast in-situ RC stair flights and landings)", "m3", 195.0, 1_180.0, {"knr": "KNR 2-02 0219-01", "din276": "350"}),
                ("3.5", "Płyty balkonowe wspornikowe z łącznikami termoizolacyjnymi (Cantilever balcony slabs with thermal break connectors)", "m2", 1_850.0, 680.0, {"knr": "KNR 2-02 0214-02", "din276": "350"}),
                ("3.6", "Zbrojenie konstrukcji nadziemia stalą B500SP, przygotowanie i montaż (Reinforcement B500SP to superstructure, cut, bend and fix)", "t", 640.0, 5_600.0, {"knr": "KNR 2-02 0290-03", "din276": "350"}),
                ("3.7", "Deskowanie systemowe ścian, słupów i schodów (System formwork to walls, columns and stairs)", "m2", 22_400.0, 78.0, {"knr": "KNR 2-02 0207-02", "din276": "350"}),
                ("3.8", "Deskowanie systemowe stropów i podciągów wraz z podporami (System formwork to slabs and beams including props)", "m2", 13_200.0, 92.0, {"knr": "KNR 2-02 0213-01", "din276": "350"}),
                ("3.9", "Pielęgnacja betonu, badania próbek i geodezyjna obsługa konstrukcji (Concrete curing, cube testing and survey control of the frame)", "kpl", 1.0, 148_000.0, {"knr": "KNR 2-02 0295-01", "din276": "350"}),
            ],
        ),
        (
            "04",
            "Dział 4. Ściany murowane i ścianki działowe (Masonry and partitions)",
            {"knr": "KNR 2-02", "din276": "340"},
            [
                ("4.1", "Ściany zewnętrzne z bloczków silikatowych grubości 24 cm na zaprawie cienkowarstwowej (External sand-lime block walls, 24 cm, thin-bed mortar)", "m2", 2_850.0, 165.0, {"knr": "KNR 2-02 0121-03", "din276": "340"}),
                ("4.2", "Ścianki działowe z bloczków silikatowych grubości 12 cm (Sand-lime block partitions, 12 cm)", "m2", 9_600.0, 128.0, {"knr": "KNR 2-02 0126-04", "din276": "340"}),
                ("4.3", "Ścianki działowe z płyt gipsowo-kartonowych na ruszcie stalowym, poszycie podwójne (Plasterboard partitions on metal studs, double lined)", "m2", 3_400.0, 195.0, {"knr": "KNR 2-02 2003-02", "din276": "340"}),
                ("4.4", "Nadproża prefabrykowane i stalowe nad otworami (Precast and steel lintels over openings)", "szt", 620.0, 185.0, {"knr": "KNR 2-02 0128-02", "din276": "340"}),
                ("4.5", "Obudowy pionów instalacyjnych z płyt gipsowo-kartonowych ognioochronnych EI30 (Fire-rated plasterboard casings to service risers, EI30)", "m2", 2_100.0, 235.0, {"knr": "KNR 2-02 2005-03", "din276": "340"}),
                ("4.6", "Attyki, ścianki kolankowe i zabudowy na poziomie dachu (Parapets, knee walls and roof-level upstands)", "m2", 780.0, 210.0, {"knr": "KNR 2-02 0130-01", "din276": "340"}),
                ("4.7", "Ścianki działowe z płyt gipsowo-kartonowych wodoodpornych w łazienkach (Moisture-resistant plasterboard partitions to bathrooms)", "m2", 1_650.0, 205.0, {"knr": "KNR 2-02 2003-06", "din276": "340"}),
                ("4.8", "Zabudowa murowana szybów dźwigowych i pomieszczeń technicznych (Masonry enclosures to lift shafts and plant rooms)", "m2", 920.0, 178.0, {"knr": "KNR 2-02 0126-08", "din276": "340"}),
            ],
        ),
        (
            "05",
            "Dział 5. Elewacja, stolarka i dach (Facade, joinery and roof)",
            {"knr": "KNR 0-33", "din276": "330"},
            [
                ("5.1", "Bezspoinowy system ocieplenia ścian, styropian EPS 20 cm, wyprawa silikonowa (ETICS render system, EPS 200 mm, silicone finish)", "m2", 4_150.0, 245.0, {"knr": "KNR 0-33 0101-05", "din276": "330"}),
                ("5.2", "Okładzina elewacyjna wentylowana z płyt włóknocementowych na ruszcie aluminiowym (Ventilated fibre-cement rainscreen on aluminium subframe)", "m2", 860.0, 620.0, {"knr": "KNR 2-02 2602-01", "din276": "330"}),
                ("5.3", "Stolarka okienna PVC z pakietem trzyszybowym Uw do 0,90 W/(m2K) (uPVC windows, triple glazed, Uw up to 0.90)", "m2", 1_480.0, 1_150.0, {"knr": "KNR 2-02 1017-02", "din276": "330"}),
                ("5.4", "Drzwi balkonowe i tarasowe PVC oraz aluminiowe (uPVC and aluminium balcony and terrace doors)", "m2", 420.0, 1_380.0, {"knr": "KNR 2-02 1017-05", "din276": "330"}),
                ("5.5", "Witryny i drzwi wejściowe aluminiowe do klatek i lokali usługowych (Aluminium entrance screens and doors to cores and retail units)", "m2", 340.0, 1_850.0, {"knr": "KNR 2-02 1019-03", "din276": "330"}),
                ("5.6", "Pokrycie dachu papą termozgrzewalną w dwóch warstwach na styropapie 25 cm (Two-layer torched bituminous roof on 250 mm insulated deck)", "m2", 1_650.0, 285.0, {"knr": "KNR 2-02 0504-02", "din276": "330"}),
                ("5.7", "Obróbki blacharskie, rynny i rury spustowe z blachy powlekanej (Coated-steel flashings, gutters and downpipes)", "m", 1_250.0, 145.0, {"knr": "KNR 2-02 0518-03", "din276": "330"}),
                ("5.8", "Balustrady balkonowe stalowo-szklane mocowane do czoła płyty (Steel and glass balcony balustrades, slab-edge fixed)", "m", 1_420.0, 780.0, {"knr": "KNR 2-02 1601-04", "din276": "330"}),
                ("5.9", "Okna oddymiające i naświetla klatek schodowych z siłownikami (Smoke-vent windows and stair rooflights with actuators)", "szt", 12.0, 8_600.0, {"knr": "KNR 2-02 1017-09", "din276": "330"}),
                ("5.10", "Ocieplenie stropu nad garażem wełną mineralną 15 cm od spodu (Mineral wool insulation to the soffit over the car park, 150 mm)", "m2", 2_750.0, 128.0, {"knr": "KNR 0-33 0401-02", "din276": "330"}),
                ("5.11", "Bramy garażowe segmentowe z napędem i kontrolą wjazdu (Sectional garage doors with drive and entry control)", "szt", 2.0, 42_000.0, {"knr": "KNR 2-02 1021-03", "din276": "330"}),
            ],
        ),
        (
            "06",
            "Dział 6. Roboty wykończeniowe (Internal finishes)",
            {"knr": "KNR 2-02", "din276": "340"},
            [
                ("6.1", "Tynki gipsowe maszynowe wewnętrzne kategorii III (Machine-applied internal gypsum plaster, category III)", "m2", 46_500.0, 42.0, {"knr": "KNR 2-02 0815-02", "din276": "340"}),
                ("6.2", "Wylewki anhydrytowe grubości 6 cm na izolacji akustycznej i termicznej (Anhydrite screed 60 mm on acoustic and thermal layer)", "m2", 11_200.0, 112.0, {"knr": "KNR 2-02 1101-07", "din276": "340"}),
                ("6.3", "Posadzki z płytek gresowych w częściach wspólnych i lokalach usługowych (Porcelain tile floors to common areas and retail units)", "m2", 3_200.0, 195.0, {"knr": "KNR 2-02 1118-02", "din276": "340"}),
                ("6.4", "Malowanie farbami akrylowymi klatek schodowych i korytarzy (Acrylic paint to stair cores and corridors)", "m2", 14_200.0, 32.0, {"knr": "KNR 2-02 1505-03", "din276": "340"}),
                ("6.5", "Sufity podwieszane z płyt gipsowo-kartonowych w holach i korytarzach (Plasterboard suspended ceilings to lobbies and corridors)", "m2", 2_400.0, 165.0, {"knr": "KNR 2-02 2007-01", "din276": "340"}),
                ("6.6", "Drzwi wejściowe do mieszkań w klasie odporności na włamanie RC2, EI30 (Flat entrance doors, burglary resistance RC2, EI30)", "szt", 128.0, 1_850.0, {"knr": "KNR 2-02 1018-02", "din276": "340"}),
                ("6.7", "Drzwi przeciwpożarowe EI30 i EI60 oraz klapy rewizyjne (Fire doors EI30 and EI60 and access hatches)", "szt", 210.0, 2_150.0, {"knr": "KNR 2-02 1018-06", "din276": "340"}),
                ("6.8", "Posadzka utwardzana powierzchniowo w garażu z oznakowaniem miejsc postojowych (Surface-hardened garage floor with bay marking)", "m2", 2_750.0, 105.0, {"knr": "KNR 2-02 1110-04", "din276": "340"}),
                ("6.9", "Balustrady i pochwyty klatek schodowych ze stali malowanej proszkowo (Stair balustrades and handrails, powder-coated steel)", "m", 380.0, 620.0, {"knr": "KNR 2-02 1601-02", "din276": "340"}),
                ("6.10", "Wyposażenie holi, skrzynki na listy, tablice informacyjne i wycieraczki systemowe (Lobby fit-out, letterboxes, notice boards and matwells)", "kpl", 2.0, 68_000.0, {"knr": "KNR 2-02 1620-01", "din276": "340"}),
                ("6.11", "Posadzki i malowanie komórek lokatorskich oraz pomieszczeń technicznych (Floors and painting to tenant storage and plant rooms)", "m2", 1_420.0, 78.0, {"knr": "KNR 2-02 1101-02", "din276": "340"}),
            ],
        ),
        (
            "07",
            "Dział 7. Instalacje sanitarne i wentylacja (Sanitary, heating and ventilation installations)",
            {"knr": "KNR 2-15", "din276": "410"},
            [
                ("7.1", "Instalacja wodociągowa, piony i podejścia z rur PP i PEX w otulinie (Water supply installation, PP and PEX risers and branches, insulated)", "m", 6_800.0, 78.0, {"knr": "KNR 2-15 0112-03", "din276": "410"}),
                ("7.2", "Instalacja kanalizacji sanitarnej z rur PVC z pionami żeliwnymi (Foul drainage installation, PVC with cast-iron risers)", "m", 5_400.0, 92.0, {"knr": "KNR 2-15 0208-04", "din276": "410"}),
                ("7.3", "Instalacja kanalizacji deszczowej podciśnieniowej z dachu (Siphonic rainwater drainage from roof)", "m", 620.0, 165.0, {"knr": "KNR 2-15 0211-02", "din276": "410"}),
                ("7.4", "Węzeł cieplny kompaktowy dwufunkcyjny o mocy 1,2 MW przyłączony do sieci miejskiej (Compact two-circuit heat substation, 1.2 MW, district heating)", "kpl", 1.0, 385_000.0, {"knr": "KNR 2-15 0405-01", "din276": "410"}),
                ("7.5", "Instalacja centralnego ogrzewania, rury wielowarstwowe w systemie rozdzielaczowym (Heating installation, multilayer pipe, manifold system)", "m", 12_400.0, 62.0, {"knr": "KNR 2-15 0403-05", "din276": "410"}),
                ("7.6", "Grzejniki płytowe z zaworami termostatycznymi (Panel radiators with thermostatic valves)", "szt", 720.0, 620.0, {"knr": "KNR 2-15 0409-03", "din276": "410"}),
                ("7.7", "Rozdzielacze mieszkaniowe z ciepłomierzami i wodomierzami zdalnego odczytu (Flat manifolds with remote-read heat and water meters)", "kpl", 128.0, 2_850.0, {"knr": "KNR 2-15 0412-02", "din276": "410"}),
                ("7.8", "Wentylacja mechaniczna wywiewna mieszkań z wentylatorami dachowymi (Mechanical extract ventilation to flats with roof fans)", "kpl", 1.0, 985_000.0, {"knr": "KNR 2-17 0101-04", "din276": "410"}),
                ("7.9", "Wentylacja bytowa i oddymiająca garażu podziemnego z detekcją CO (Car park supply, extract and smoke ventilation with CO detection)", "kpl", 1.0, 720_000.0, {"knr": "KNR 2-17 0138-02", "din276": "410"}),
                ("7.10", "Instalacja hydrantowa wewnętrzna DN25 oraz oddymianie klatek schodowych (Internal DN25 hydrant main and stair smoke ventilation)", "kpl", 1.0, 605_000.0, {"knr": "KNR 2-15 0125-03", "din276": "410"}),
                ("7.11", "Próby szczelności, płukanie, dezynfekcja i regulacja hydrauliczna instalacji (Pressure testing, flushing, disinfection and hydraulic balancing)", "kpl", 1.0, 186_000.0, {"knr": "KNR 2-15 0135-01", "din276": "410"}),
            ],
        ),
        (
            "08",
            "Dział 8. Instalacje elektryczne, teletechniczne i dźwigi (Electrical, ELV and lifts)",
            {"knr": "KNR 5-08", "din276": "440"},
            [
                ("8.1", "Złącze kablowe i rozdzielnica główna niskiego napięcia (Service head and main LV distribution board)", "kpl", 1.0, 285_000.0, {"knr": "KNR 5-08 0301-02", "din276": "440"}),
                ("8.2", "Wewnętrzne linie zasilające i rozdzielnice mieszkaniowe (Rising mains and flat consumer units)", "kpl", 128.0, 1_650.0, {"knr": "KNR 5-08 0212-03", "din276": "440"}),
                ("8.3", "Instalacje elektryczne w mieszkaniach, gniazda, oświetlenie i osprzęt (Electrical installation within flats, sockets, lighting and accessories)", "m2", 8_900.0, 145.0, {"knr": "KNR 5-08 0102-04", "din276": "440"}),
                ("8.4", "Oprawy oświetleniowe LED z czujnikami ruchu w częściach wspólnych i garażu (LED luminaires with presence detection to common areas and garage)", "szt", 940.0, 285.0, {"knr": "KNR 5-08 0511-03", "din276": "440"}),
                ("8.5", "Oświetlenie awaryjne i ewakuacyjne zasilane z centralnej baterii (Emergency and escape lighting on a central battery system)", "szt", 320.0, 420.0, {"knr": "KNR 5-08 0512-01", "din276": "440"}),
                ("8.6", "Instalacja odgromowa, uziemienia i połączenia wyrównawcze (Lightning protection, earthing and equipotential bonding)", "m", 1_850.0, 62.0, {"knr": "KNR 5-08 0611-02", "din276": "440"}),
                ("8.7", "Instalacje teletechniczne, domofon, telewizja dozorowa, kontrola dostępu i sieć światłowodowa (ELV installations, entry phone, CCTV, access control and fibre network)", "kpl", 1.0, 745_000.0, {"knr": "KNR 5-08 0703-04", "din276": "440"}),
                ("8.8", "Dźwigi osobowe 630 kg z dojazdem do garażu, dostawa, montaż i uruchomienie (Passenger lifts 630 kg serving the car park, supply, install and commission)", "szt", 4.0, 385_000.0, {"knr": "KNR 7-01 0201-03", "din276": "440"}),
                ("8.9", "Punkty ładowania pojazdów elektrycznych w garażu wraz z infrastrukturą kanałową (EV charging points in the car park with containment infrastructure)", "szt", 20.0, 12_400.0, {"knr": "KNR 5-08 0415-02", "din276": "440"}),
                ("8.10", "Przeciwpożarowy wyłącznik prądu i rozdzielnice pożarowe (Fire-service main switch and fire-rated distribution boards)", "kpl", 1.0, 96_000.0, {"knr": "KNR 5-08 0305-04", "din276": "440"}),
                ("8.11", "Instalacja fotowoltaiczna na dachu o mocy 40 kWp na potrzeby części wspólnych (Rooftop 40 kWp photovoltaic array serving the common areas)", "kpl", 1.0, 285_000.0, {"knr": "KNR 5-08 0810-01", "din276": "440"}),
            ],
        ),
        (
            "09",
            "Dział 9. Sieci zewnętrzne i zagospodarowanie terenu (External services and site works)",
            {"knr": "KNR 2-18", "din276": "500"},
            [
                ("9.1", "Przyłącza wodociągowe i kanalizacyjne do sieci miejskiej (Water and sewer connections to the city mains)", "m", 220.0, 620.0, {"knr": "KNR 2-18 0102-03", "din276": "500"}),
                ("9.2", "Przyłącze ciepłownicze preizolowane do węzła cieplnego (Pre-insulated district heating connection to the substation)", "m", 120.0, 1_450.0, {"knr": "KNR 2-18 0501-02", "din276": "500"}),
                ("9.3", "Nawierzchnie z kostki betonowej, drogi wewnętrzne i miejsca postojowe (Concrete block paving, internal roads and parking bays)", "m2", 2_100.0, 185.0, {"knr": "KNR 2-31 0511-03", "din276": "500"}),
                ("9.4", "Chodniki i opaski przy budynku z płyt betonowych (Footways and perimeter aprons in concrete slabs)", "m2", 1_250.0, 145.0, {"knr": "KNR 2-31 0511-01", "din276": "500"}),
                ("9.5", "Zieleń urządzona, trawniki, nasadzenia drzew i krzewów z nawadnianiem (Soft landscaping, lawns, tree and shrub planting with irrigation)", "m2", 1_850.0, 165.0, {"knr": "KNR 2-21 0401-02", "din276": "500"}),
                ("9.6", "Plac zabaw, mała architektura, wiaty rowerowe i osłona śmietnikowa (Playground, site furniture, bicycle shelters and bin store)", "kpl", 1.0, 385_000.0, {"knr": "KNR 2-21 0701-01", "din276": "500"}),
                ("9.7", "Ogrodzenie terenu panelowe z bramą wjazdową i furtkami (Panel site fencing with vehicle gate and wickets)", "m", 210.0, 420.0, {"knr": "KNR 2-21 0801-02", "din276": "500"}),
                ("9.8", "Oświetlenie terenu latarniami LED wraz z kablowaniem (External LED lighting columns and cabling)", "szt", 26.0, 4_850.0, {"knr": "KNR 5-08 0521-03", "din276": "500"}),
            ],
        ),
    ],
    # Polish price build-up. A kosztorys szczegółowy takes koszty pośrednie on
    # robocizna plus sprzęt and zysk on robocizna, sprzęt and koszty pośrednie,
    # never on the whole direct cost. This template has one base to offer, so
    # the two percentages below are equivalents that land the same money:
    # see project_metadata["markup_base_note"]. VAT is 8 percent because the
    # works are the construction of a residential building under the social
    # housing programme, not the 23 percent standard rate.
    markups=[
        ("Koszty pośrednie (Indirect costs, Kp)", 18.0, "overhead", "direct_cost"),
        ("Zysk (Profit, Z)", 8.0, "profit", "cumulative"),
        ("Rezerwa na roboty nieprzewidziane (Contingency)", 3.0, "contingency", "cumulative"),
        ("Podatek VAT 8 procent (VAT at 8 percent, social housing programme rate)", 8.0, "tax", "cumulative"),
    ],
    total_months=24,
    tender_name="Generalne wykonawstwo - budynek mieszkalny Wola (Main contract, residential building)",
    tender_companies=[
        ("Przedsiębiorstwo Budowlane Zaporzecze", "przetargi@zaporzecze.example", 0.98),
        ("Grupa Budowlana Miłostki", "oferty@milostki.example", 1.04),
        ("Zakład Ogólnobudowlany Skarbniczyn", "przetargi@skarbniczyn.example", 1.01),
    ],
    tender_packages=[
        (
            "Stan zerowy i konstrukcja żelbetowa (Substructure and RC frame)",
            "Roboty ziemne, obudowa wykopu, płyta fundamentowa, kondygnacja podziemna i konstrukcja nadziemia.",
            "evaluating",
            [
                ("Przedsiębiorstwo Budowlane Zaporzecze", "przetargi@zaporzecze.example", 0.98),
                ("Grupa Budowlana Miłostki", "oferty@milostki.example", 1.04),
                ("Zakład Ogólnobudowlany Skarbniczyn", "przetargi@skarbniczyn.example", 1.01),
            ],
        ),
        (
            "Elewacja, stolarka i dach (Facade, joinery and roof)",
            "System ocieplenia, okładzina wentylowana, stolarka okienna i drzwiowa, pokrycie dachu i obróbki.",
            "issued",
            [
                ("Elewacje i Fasady Wietrznica", "przetargi@wietrznica.example", 0.99),
                ("Stolarka Otworowa Podgrodzie", "oferty@podgrodzie.example", 1.05),
                ("Zakład Ogólnobudowlany Skarbniczyn", "przetargi@skarbniczyn.example", 1.02),
            ],
        ),
        (
            "Instalacje sanitarne i elektryczne (Sanitary and electrical installations)",
            "Woda, kanalizacja, centralne ogrzewanie, wentylacja, instalacje elektryczne, teletechnika i dźwigi.",
            "issued",
            [
                ("Instalacje Sanitarne Wiatrołuż", "przetargi@wiatroluz.example", 0.97),
                ("Elektromontaż Nowe Zamłynie", "oferty@zamlynie.example", 1.03),
                ("Przedsiębiorstwo Instalacyjne Perzanka", "przetargi@perzanka.example", 1.01),
            ],
        ),
    ],
    schedule_activities=[
        ("Zagospodarowanie placu budowy (Site setup and enabling works)", "2026-03-02", "2026-04-17"),
        ("Roboty ziemne i obudowa wykopu (Earthworks and excavation support)", "2026-04-01", "2026-07-31"),
        ("Płyta fundamentowa i izolacje (Raft foundation and tanking)", "2026-07-01", "2026-10-30"),
        ("Konstrukcja kondygnacji podziemnej (Basement structure)", "2026-09-01", "2026-12-31"),
        ("Konstrukcja żelbetowa nadziemia (Superstructure frame)", "2026-12-01", "2027-08-31"),
        ("Ściany murowane i ścianki działowe (Masonry and partitions)", "2027-03-01", "2027-10-29"),
        ("Dach i pokrycie (Roof and waterproofing)", "2027-07-01", "2027-09-30"),
        ("Stolarka okienna i drzwiowa zewnętrzna (Windows and external doors)", "2027-06-01", "2027-10-29"),
        ("Elewacja i system ocieplenia (Facade and external wall insulation)", "2027-08-02", "2027-12-31"),
        ("Instalacje sanitarne i wentylacja (Sanitary, heating and ventilation)", "2027-04-01", "2027-12-31"),
        ("Instalacje elektryczne i teletechniczne (Electrical and ELV installations)", "2027-04-01", "2027-12-31"),
        ("Montaż i odbiór dźwigów (Lift installation and inspection)", "2027-09-01", "2027-12-15"),
        ("Roboty wykończeniowe (Internal finishes)", "2027-09-01", "2028-01-31"),
        ("Zagospodarowanie terenu i sieci zewnętrzne (Site works and external services)", "2027-10-01", "2028-01-31"),
        ("Odbiory i pozwolenie na użytkowanie (Handover and occupancy permit)", "2028-01-04", "2028-02-28"),
    ],
    project_metadata={
        "address": "ulica Marcina Kasprzaka 29, 01-234 Warszawa, Polska",
        "client": "Zaporzecka Grupa Deweloperska sp. z o.o.",
        "architect": "Pracownia Architektoniczna Wiślany Brzeg",
        "quantity_surveyor": "Biuro Kosztorysowe Ostrowiecka",
        "structural_engineer": "Biuro Konstrukcyjne Przęsło Warszawa",
        "gfa_m2": 14800,
        "site_area_m2": 5400,
        "storeys": 8,
        "basement_levels": 1,
        "flats": 128,
        "usable_flat_area_m2": 8900,
        "retail_units": 2,
        "parking_spaces": 96,
        "construction_standards": [
            "Rozporządzenie Ministra Infrastruktury z 12.04.2002 w sprawie warunków technicznych, jakim powinny odpowiadać budynki i ich usytuowanie",
            "Ustawa Prawo budowlane (Dz.U. 1994 nr 89 poz. 414, z późniejszymi zmianami)",
            "PN-EN 1992-1-1 Eurokod 2, konstrukcje z betonu, z załącznikiem krajowym",
            "PN-EN 1997-1 Eurokod 7, projektowanie geotechniczne",
            "PN-B-02151-3 Izolacyjność akustyczna przegród w budynkach",
            "Rozporządzenie MSWiA w sprawie ochrony przeciwpożarowej budynków, budynek ZL IV, klasa odporności pożarowej B",
        ],
        "estimating_method": (
            "Kalkulacja szczegółowa: nakłady rzeczowe z katalogów KNR, ceny czynników produkcji z rynku "
            "warszawskiego. Podstawa formalna to Rozporządzenie Ministra Rozwoju i Technologii z 20 grudnia "
            "2021 r. w sprawie metod i podstaw sporządzania kosztorysu inwestorskiego (Dz.U. 2021 poz. 2458). "
            "Detailed calculation method: resource inputs from the KNR catalogues, factor prices from the "
            "Warsaw market, under the 2021 regulation on the investor's estimate."
        ),
        "regulator": (
            "Wydział Architektury i Budownictwa Urzędu m.st. Warszawy dla pozwolenia na budowę; Powiatowy "
            "Inspektorat Nadzoru Budowlanego dla m.st. Warszawy dla zawiadomienia o zakończeniu budowy i "
            "pozwolenia na użytkowanie. Kierownik budowy prowadzi dziennik budowy przez cały czas robót. "
            "Building permit from the city architecture department, completion and occupancy from the county "
            "building inspectorate; the site manager keeps the statutory site diary throughout."
        ),
        "estimate_type_note": (
            "Ten dokument jest kosztorysem inwestorskim: sporządza go zamawiający, żeby ustalić wartość "
            "zamówienia, i jego metoda oraz podstawy są uregulowane rozporządzeniem. Kosztorys ofertowy to "
            "inny dokument: sporządza go wykonawca na tym samym przedmiarze, ale wycenia go własnymi cenami, "
            "których nikt nie reguluje, i to on staje się załącznikiem do umowy. Dwa dokumenty o tej samej "
            "strukturze pełnią przeciwne role, więc mylenie ich zmienia sens liczby. "
            "This is an investor's estimate, prepared by the employer to establish the value of the "
            "procurement, with its method and bases set by regulation. A contractor's tender estimate is a "
            "different document: same measured quantities, the bidder's own unregulated prices, and it is the "
            "one that becomes a contract annex."
        ),
        "markup_base_note": (
            "Koszty pośrednie normuje się w Polsce od sumy robocizny i pracy sprzętu, a zysk od robocizny, "
            "sprzętu i kosztów pośrednich, nie od całego kosztu bezpośredniego. Wskaźniki rynkowe dla robót "
            "ogólnobudowlanych to około 60-70 procent dla Kp i 10-12 procent dla Z liczone od tych baz. "
            "Narzuty w tym szablonie liczą się od kosztu bezpośredniego i od sumy narastającej, dlatego "
            "wpisano procenty równoważne: suma wychodzi ta sama, ale wrażliwość na udział R i S w pozycji "
            "znika. Kosztorysant, który chce prawdziwej struktury, musi rozbić ceny jednostkowe na R, M i S. "
            "Indirect costs in Poland are normed on labour plus plant and profit on labour, plant and "
            "indirect costs, never on the whole direct cost; the percentages here are equivalents against "
            "direct cost, so the totals match and the sensitivity to the labour and plant share is lost."
        ),
        "vat_note": (
            "Stawka 8 procent wynika z art. 41 ust. 12 ustawy o VAT: budowa obiektu objętego społecznym "
            "programem mieszkaniowym. Budynek jest sklasyfikowany w PKOB 1122, a ponad połowa powierzchni "
            "użytkowej jest mieszkalna, więc stawka obniżona obejmuje roboty dotyczące całej bryły, w tym "
            "garaż podziemny i lokale usługowe w parterze. Uwaga na granicę: infrastruktura towarzysząca "
            "poza bryłą budynku, czyli drogi, przyłącza i zagospodarowanie terenu, jest opodatkowana stawką "
            "23 procent. Ten kosztorys stosuje jedną linię 8 procent do całości, co dla działu 9 zaniża "
            "podatek i przed użyciem wymaga rozdzielenia. "
            "The 8 percent rate follows from the social housing programme provision of the VAT act; the "
            "building is PKOB 1122 and more than half its usable area is residential, so the reduced rate "
            "covers the whole envelope. External infrastructure outside the envelope is taxed at 23 percent, "
            "and this estimate applies a single 8 percent line, which understates the tax on section 9."
        ),
        "price_source_note": (
            "Ceny czynników produkcji w polskim kosztorysowaniu bierze się z kwartalnych biuletynów cenowych "
            "wydawanych przez ośrodki cenowe: ceny materiałów, stawki robocizny kosztorysowej i ceny pracy "
            "sprzętu, a dla wycen uproszczonych wskaźniki cenowe obiektów i asortymentów robót. "
            "Rozporządzenie o kosztorysie inwestorskim wprost dopuszcza takie publikacje jako podstawę, obok "
            "danych rynkowych z zawartych umów, a kalkulację własną dopiero wtedy, gdy ani katalog, ani "
            "publikacja nie dają pozycji. Ceny w tym kosztorysie są oszacowaniem rynkowym, a nie odczytem "
            "z biuletynu, i to jest pierwsza rzecz do podmiany. "
            "Polish estimating reads its factor prices from quarterly price bulletins published by cost-data "
            "houses, and the investor's estimate regulation names such publications as an acceptable basis "
            "alongside market data from concluded contracts. The rates here are market estimates rather than "
            "bulletin readings, which is the first thing a local estimator should replace."
        ),
        "technical_conditions_note": (
            "Warunki Techniczne w brzmieniu obowiązującym od 31 grudnia 2020 r. wymagają dla budynku "
            "wielorodzinnego wskaźnika EP nie większego niż 65 kWh/(m2 rok) oraz współczynników przenikania "
            "ciepła U do 0,20 dla ścian, 0,15 dla dachu i 0,90 dla okien. Stąd 20 cm styropianu na elewacji i "
            "pakiet trzyszybowy w pozycji 5.3, a nie z upodobania projektanta. Nowelizacja obowiązująca od "
            "1 sierpnia 2024 r. dołożyła między innymi pomieszczenie na wózki i rowery, przegrody między "
            "balkonami sąsiednich mieszkań oraz zaostrzone wymagania dla placu zabaw; zakres tej nowelizacji "
            "należy zweryfikować z aktualnym tekstem, bo ten kosztorys uwzględnia ją tylko ryczałtowo w "
            "pozycjach 4.6 i 9.6. "
            "The technical conditions in force since 31 December 2020 cap primary energy at 65 kWh/(m2 year) "
            "for multi-family buildings and set U-values of 0.20 for walls, 0.15 for roofs and 0.90 for "
            "windows, which is where the 200 mm insulation and triple glazing come from. The August 2024 "
            "amendment added a pram and bicycle room, partitions between neighbouring balconies and stricter "
            "playground rules; it is covered here only as a lump in items 4.6 and 9.6 and should be checked "
            "against the current text."
        ),
        "fire_safety_note": (
            "Budynek średniowysoki w kategorii zagrożenia ludzi ZL IV nie wymaga systemu sygnalizacji "
            "pożarowej w części mieszkalnej, dlatego w dziale 8 go nie ma. Wymagane są natomiast oddymianie "
            "klatek schodowych, hydranty wewnętrzne i detekcja tlenku węgla w garażu, i te pozycje stoją w "
            "dziale 7. A medium-height ZL IV residential building needs no fire-alarm system in the "
            "residential part, which is why section 8 carries none; stair smoke ventilation, internal "
            "hydrants and car park CO detection are required and sit in section 7."
        ),
        "delivery_standard_note": (
            "Mieszkania przekazywane w standardzie deweloperskim: tynki, wylewki, stolarka okienna, drzwi "
            "wejściowe i instalacje zakończone bez białego montażu, bez posadzek i bez malowania wnętrz "
            "mieszkań. Dlatego posadzki i malowanie w dziale 6 obejmują tylko części wspólne i lokale "
            "usługowe. Flats are handed over to Polish developer standard, so the floor finishes and "
            "painting in section 6 cover common areas and retail units only."
        ),
        "contract": "Umowa o generalne wykonawstwo z wynagrodzeniem ryczałtowym (lump-sum main contract)",
        "headline_cost_pln": "Około 65 mln zł netto, 70,6 mln zł brutto (approx. PLN 65 million net)",
    },
    budget_boq_name="Budżet kontrolny inwestycji (Control budget)",
    planned_budget=65_000_000.0,
    actual_spend_ratio=0.28,
    spi_override=0.99,
    cpi_override=1.02,
    # Detailed build-up of the double-lined plasterboard partition as a Polish
    # cost estimate writes it: quantities per m2 of wall (cutting waste
    # included) at Warsaw merchant prices 2026, and the crew's hours per m2 at
    # the average labour-hour rate. The rows add up to the unit rate exactly.
    position_resources={
        # CW 75, two layers of 12.5 mm board each side, mineral wool in the cavity.
        "4.3": [
            ("drywall_cw_stud_75", "material", "m", 2.00, 9.20),
            ("drywall_uw_track_75", "material", "m", 0.80, 8.10),
            ("drywall_board_gkb_12_5", "material", "m2", 4.20, 15.80),
            ("drywall_mineral_wool", "material", "m2", 1.05, 11.40),
            ("drywall_screws", "material", "szt", 40, 0.0525),
            ("drywall_joint_compound", "material", "kg", 0.60, 4.80),
            ("drywall_sealing_tape", "material", "m", 1.20, 1.40),
            ("drywall_anchors", "material", "szt", 1.60, 0.45),
            ("drywall_installer_avg_wage", "labor", "hr", 1.15, 72.00),
            ("drywall_small_tools", "equipment", "hr", 1.15, 1.40),
        ],
    },
)
