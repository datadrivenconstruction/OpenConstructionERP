# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: italy-voci - Edificio residenziale, Roma (Residential building, Rome)
# ---------------------------------------------------------------------------
# An Italian estimate is a computo metrico estimativo: measured quantities
# against an elenco prezzi, priced from the prezzario regionale that the
# region publishes for public works and that private developers use as the
# reference the market argues against. Every line below carries a voce code
# in the shape chapter.group.article.variant, for example A.01.010.a, which
# is how a Lazio or DEI style price book addresses a single article.
#
# What is indicative here, and what a local estimator has to replace before
# this bill is used for real work.
#
# 1. The codes are correctly shaped, not published. Chapter letters follow a
#    condensed reading of the usual prezzario order: A opere provvisionali,
#    B scavi e fondazioni, C strutture, D murature, E involucro, F finiture,
#    G impianti meccanici, H impianti elettrici ed elevatori, I opere
#    esterne. Each item sits in the right chapter and the code has the right
#    shape, but the article numbers are not taken from the published Lazio
#    edition, because we do not hold that text. Re-point every code at the
#    edition in force before the bill goes near a tender.
#
# 2. The rates are direct cost, not prezzario prices. A prezzario price
#    already contains spese generali and utile d'impresa at the conventional
#    15 and 10 per cent, which compound to 1.15 x 1.10 = 1.265. This
#    template carries spese generali and utile as markup lines, so the rates
#    below are the listed price divided by 1.265 and nothing is counted
#    twice. A reader comparing a line against the prezzario should multiply
#    it back by 1.265 first. Levels are Rome 2026 in euro, net of IVA, and
#    they are market estimates rather than quotations.
#
# 3. The statutory figures are cited from the decree, not measured. The
#    seismic parameters for the site, the labour congruity incidence under
#    DM 143/2021 and the photovoltaic coefficient under D.Lgs. 199/2021
#    Allegato III are stated so a reader can see which rules bind a Rome
#    residential building. Each one has to be recomputed for the actual site
#    and against the edition in force on the day.
#
# 4. IVA is 10 per cent because that is the rate for a contract to build a
#    non-luxury residential building. It is 4 per cent where the contract is
#    for a prima casa and 22 per cent otherwise, so the rate is a property
#    of the buyer rather than of the building. Subcontracts inside the
#    construction chain run under reverse charge and carry no IVA at all,
#    which is why only one tax line appears here.
#
# 5. The validation rule sets are the two registered generic ones. The
#    Italian set, "italy", is not named here: validating the bill adds it
#    from the project's country and its "voci" standard, so naming it twice
#    would change nothing.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-rome",
    project_name="Edificio residenziale Mezzocammino - Roma (Residential Building, Rome)",
    project_description=(
        "Nuova costruzione di un edificio residenziale di 96 alloggi su due corpi scala, "
        "7 piani fuori terra e 2 piani interrati destinati ad autorimessa e cantine, "
        "nel quartiere Mezzocammino, Municipio IX, Roma. Superficie lorda complessiva "
        "circa 17.200 mq, di cui circa 12.800 mq fuori terra e 4.400 mq interrati, su "
        "un lotto di circa 6.800 mq. Struttura a telaio in cemento armato gettato in "
        "opera con nuclei di controvento, fondazione su pali trivellati e platea, "
        "progettata secondo le NTC 2018 in zona sismica 3, classe di duttilità CD B. "
        "Involucro NZEB con cappotto termico, serramenti a taglio termico e impianti "
        "interamente elettrici a pompa di calore con fotovoltaico in copertura. "
        "Computo metrico estimativo redatto sul prezzario regionale del Lazio, "
        "livello prezzi Roma 2026, importo dei lavori circa 20,8 milioni di euro "
        "oltre IVA. "
        "New-build residential block of 96 flats in two stair cores, 7 storeys above "
        "ground and 2 basement levels of parking and storage, in the Mezzocammino "
        "district of Rome. Gross area approx. 17,200 m2 (approx. 12,800 m2 above "
        "ground, 4,400 m2 below) on a 6,800 m2 plot. Cast in-situ reinforced concrete "
        "frame with shear cores on bored piles and a raft, designed to NTC 2018 for "
        "seismic zone 3. NZEB envelope, all-electric heat pump services with rooftop "
        "photovoltaics. Measured works approx. EUR 20.8 million excluding VAT, priced "
        "on the Lazio regional price book at Rome 2026 levels."
    ),
    region="IT",
    classification_standard="voci",
    currency="EUR",
    locale="it",
    project_code="RM-MZC-2026-01",
    address={
        "street": "Via di Mezzocammino 118",
        "city": "Roma",
        "postcode": "00128",
        "country": "Italy",
        "lat": 41.8083,
        "lng": 12.4579,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    boq_name="Computo metrico estimativo - Prezzario Regione Lazio (Bill of Quantities)",
    boq_description=(
        "Computo metrico estimativo per categorie di lavoro, redatto sull'elenco prezzi "
        "del prezzario regionale delle opere pubbliche del Lazio e integrato con analisi "
        "dei prezzi per le voci non presenti. I prezzi unitari esposti sono costi diretti "
        "al netto di spese generali e utile d'impresa, che compaiono come voci di "
        "incidenza in calce al computo. Livello prezzi Roma 2026, IVA esclusa. "
        "Bill of quantities by work category on the Lazio regional price book. Unit "
        "rates are direct cost net of overheads and profit, which are carried as "
        "separate build-up lines. Rome 2026 price level, VAT excluded."
    ),
    boq_metadata={
        "standard": "Prezzario Regionale delle Opere Pubbliche della Regione Lazio",
        "phase": "Progetto esecutivo - computo metrico estimativo (Detailed design estimate)",
        "base_date": "2026-Q1",
        "price_level": "Roma 2026 (Rome 2026)",
        "pricing_method": "Computo metrico estimativo su elenco prezzi, costi diretti al netto di spese generali e utile",
    },
    sections=[
        (
            "A",
            "Cap. A - Opere provvisionali e allestimento del cantiere (Temporary works and site set-up)",
            {"voci": "A"},
            [
                ("A.1", "Recinzione di cantiere in pannelli grigliati h 2,00 m su basi in calcestruzzo, compresi montaggio, nolo per la durata dei lavori e smontaggio (Site hoarding, erect, hire and dismantle)", "m", 340.0, 24.50, {"voci": "A.01.010.a"}),
                ("A.2", "Baraccamenti di cantiere: uffici della direzione lavori, spogliatoi, servizi igienici e refettorio, allacciati alle reti provvisorie (Site accommodation, offices and welfare)", "mese", 26.0, 1_850.00, {"voci": "A.01.030.b"}),
                ("A.3", "Ponteggio metallico a telai prefabbricati fino a 24 m di altezza, compresi mantovane parasassi, teli, montaggio, nolo per dodici mesi e smontaggio (Tube and frame scaffold, 12 month hire)", "m2", 9_600.0, 19.80, {"voci": "A.02.010.a"}),
                ("A.4", "Gru a torre a rotazione alta, braccio 50 m, portata in punta 1,5 t, compresi plinto di base, montaggio, nolo mensile e smontaggio (Tower crane, base, erection, hire and dismantling)", "mese", 22.0, 4_150.00, {"voci": "A.02.030.c"}),
                ("A.5", "Impianto elettrico e idrico di cantiere con quadri ASC, illuminazione delle aree di lavoro e allacci provvisori alle reti pubbliche (Temporary site power, water and lighting)", "a corpo", 1.0, 68_000.00, {"voci": "A.03.010.a"}),
                ("A.6", "Montacarichi da cantiere a colonna, portata 500 kg, per il sollevamento dei materiali di finitura, compresi montaggio, nolo e smontaggio (Mast climbing material hoist, erection, hire and dismantling)", "mese", 14.0, 1_280.00, {"voci": "A.02.050.a"}),
                ("A.7", "Oneri di gestione ambientale del cantiere: impianto di lavaggio ruote, abbattimento delle polveri, raccolta differenziata e smaltimento dei rifiuti da costruzione (Site environmental management, wheel wash, dust suppression and waste disposal)", "mese", 26.0, 1_450.00, {"voci": "A.03.030.b"}),
            ],
        ),
        (
            "B",
            "Cap. B - Scavi, movimenti terra e opere di fondazione (Earthworks and foundations)",
            {"voci": "B"},
            [
                ("B.1", "Scavo di sbancamento con mezzi meccanici in terreni di qualsiasi natura e consistenza, compreso il carico su automezzo (Bulk excavation, machine, loaded to lorry)", "m3", 17_400.0, 6.80, {"voci": "B.01.010.a"}),
                ("B.2", "Scavo a sezione obbligata per plinti, travi rovesce e sottoservizi, anche in presenza di acqua, compresi sbadacchiature e aggottamento (Trench and pit excavation)", "m3", 1_850.0, 12.60, {"voci": "B.01.020.b"}),
                ("B.3", "Trasporto dei materiali di risulta a discarica autorizzata, compresi oneri di conferimento e caratterizzazione (Haulage and licensed tipping of spoil)", "m3", 16_200.0, 14.80, {"voci": "B.01.040.a"}),
                ("B.4", "Berlinese di micropali D 220 mm a interasse 0,60 m, lunghezza 10 m, per il sostegno dello scavo, compresa trave di coronamento in cemento armato (Micropile retaining wall with capping beam)", "m2", 1_400.0, 148.00, {"voci": "B.02.010.c"}),
                ("B.5", "Pali trivellati di grande diametro D 600 mm gettati in opera con calcestruzzo C25/30, compresi gabbia di armatura, scapitozzatura e prove di integrità (Bored piles D600, cage, trimming and testing)", "m", 4_200.0, 74.00, {"voci": "B.03.010.a"}),
                ("B.6", "Magrone di sottofondazione in calcestruzzo C12/15 dello spessore di 10 cm, gettato su vespaio drenante (Blinding concrete C12/15)", "m3", 205.0, 102.00, {"voci": "B.04.010.a"}),
                ("B.7", "Rinterro e rinfianco con materiale arido di cava, steso e costipato a strati di 30 cm fino al raggiungimento del 95 per cento della densità Proctor (Granular backfill, compacted in layers)", "m3", 3_100.0, 18.50, {"voci": "B.05.010.b"}),
                ("B.8", "Vespaio areato con casseri modulari a cupola dell'altezza di 40 cm e getto di completamento in calcestruzzo C25/30 armato con rete elettrosaldata (Ventilated void former slab 400 mm with reinforced concrete topping)", "m2", 1_850.0, 38.50, {"voci": "B.04.030.a"}),
                ("B.9", "Drenaggio perimetrale delle strutture controterra con tubo microfessurato in PEAD D 200 mm, ghiaia lavata e tessuto non tessuto di separazione (Perimeter land drain, HDPE pipe, washed gravel and geotextile)", "m", 210.0, 42.00, {"voci": "B.05.030.a"}),
            ],
        ),
        (
            "C",
            "Cap. C - Strutture in cemento armato e solai (Reinforced concrete structure and floors)",
            {"voci": "C"},
            [
                ("C.1", "Platea di fondazione in calcestruzzo C30/37 classe di esposizione XC2, spessore 60 cm, gettata con pompa autocarrata e vibrata (Raft foundation C30/37 XC2, 600 mm)", "m3", 1_150.0, 128.00, {"voci": "C.01.010.a"}),
                ("C.2", "Muri controterra dei piani interrati in calcestruzzo C32/40 XC2 con additivo idrofugo di massa, spessore 35 cm (Basement retaining walls C32/40, waterproof admixture)", "m3", 470.0, 152.00, {"voci": "C.01.030.b"}),
                ("C.3", "Pilastri e setti di controvento in calcestruzzo C32/40 XC1 in elevazione, compreso il tiro in alto (Columns and shear walls C32/40)", "m3", 690.0, 158.00, {"voci": "C.02.010.a"}),
                ("C.4", "Travi, cordoli di piano e nuclei dei vani scala e ascensore in calcestruzzo C32/40 XC1 (Beams, ring beams, stair and lift cores C32/40)", "m3", 820.0, 149.00, {"voci": "C.02.030.a"}),
                ("C.5", "Solai in latero-cemento gettati in opera H 24+4 cm con travetti tralicciati e pignatte, compresi getto di completamento e rete elettrosaldata (Clay block and concrete floor slabs 24+4)", "m2", 12_600.0, 73.50, {"voci": "C.03.010.b"}),
                ("C.6", "Solette piene in calcestruzzo armato C32/40 dello spessore di 25 cm ai piani interrati e sui locali tecnici (Solid RC slabs 250 mm, basements and plant rooms)", "m2", 3_050.0, 94.00, {"voci": "C.03.020.a"}),
                ("C.7", "Scale interne in cemento armato gettate in opera, comprese rampe, pianerottoli e travi a ginocchio (Cast in-situ RC stairs, flights and landings)", "m3", 172.0, 224.00, {"voci": "C.03.040.a"}),
                ("C.8", "Acciaio in barre ad aderenza migliorata B450C, sagomato e posto in opera, compresi sfridi, legature e distanziatori (Reinforcement B450C, cut, bent and fixed)", "kg", 860_000.0, 1.48, {"voci": "C.04.010.a"}),
                ("C.9", "Casseforme in pannelli metallici e legno per getti in elevazione, comprese puntellazioni, disarmo e pulizia (Formwork to vertical and horizontal elements)", "m2", 19_600.0, 25.50, {"voci": "C.04.030.b"}),
                ("C.10", "Giunti sismici fra i corpi di fabbrica con profili di copertura e sigillature, e appoggi in elastomero ai sensi delle NTC 2018 (Seismic movement joints and bearings to NTC 2018)", "m", 260.0, 96.00, {"voci": "C.05.010.a"}),
                ("C.11", "Prove sui materiali e controlli di accettazione del calcestruzzo e dell'acciaio, compresi prelievi, confezionamento dei provini e certificazioni di laboratorio ufficiale (Materials testing and acceptance controls, sampling, cubes and certification)", "a corpo", 1.0, 42_000.00, {"voci": "C.06.010.a"}),
            ],
        ),
        (
            "D",
            "Cap. D - Murature, tamponamenti e divisori interni (Masonry, infill walls and partitions)",
            {"voci": "D"},
            [
                ("D.1", "Tamponamento perimetrale in blocchi di laterizio porizzato dello spessore di 30 cm, in opera con malta termica e giunti rasati (Perimeter infill wall, porous clay blocks 300 mm)", "m2", 6_400.0, 53.50, {"voci": "D.01.010.a"}),
                ("D.2", "Tramezzature interne agli alloggi in laterizio forato dello spessore di 8 cm, in opera con malta bastarda (Internal partitions, hollow clay bricks 80 mm)", "m2", 9_800.0, 29.50, {"voci": "D.01.030.b"}),
                ("D.3", "Pareti divisorie fra unità immobiliari in doppia lastra di gesso rivestito su orditura metallica con doppio strato di lana minerale, potere fonoisolante Rw non inferiore a 50 dB (Party walls, double plasterboard on studs, Rw >= 50 dB)", "m2", 4_600.0, 52.00, {"voci": "D.02.010.a"}),
                ("D.4", "Contropareti isolanti interne sulle murature perimetrali, lastra in gesso rivestito su orditura con lana di roccia 60 mm (Insulated internal linings to external walls)", "m2", 5_900.0, 34.00, {"voci": "D.02.030.a"}),
                ("D.5", "Architravi prefabbricati, cordoli di ripartizione e rinforzi in muratura armata in corrispondenza delle aperture (Lintels, spreader beams and reinforced masonry to openings)", "m", 1_250.0, 38.00, {"voci": "D.03.010.b"}),
                ("D.6", "Muratura in blocchi di calcestruzzo vibrocompresso per locali tecnici, vani contatori e box cantina dei piani interrati (Concrete block walls to plant rooms, meter cupboards and basement stores)", "m2", 3_200.0, 41.00, {"voci": "D.01.050.a"}),
                ("D.7", "Compartimentazioni antincendio dei cavedi, dei filtri e dei vani scala con lastre e sigillature certificate REI 120 (Fire compartmentation to risers, lobbies and stair enclosures, certified REI 120)", "m2", 1_150.0, 68.00, {"voci": "D.04.010.a"}),
            ],
        ),
        (
            "E",
            "Cap. E - Involucro: coperture, impermeabilizzazioni, isolamenti e serramenti (Envelope, roofing, waterproofing and windows)",
            {"voci": "E"},
            [
                ("E.1", "Massetto delle pendenze in calcestruzzo alleggerito con argilla espansa, spessore medio 8 cm, staggiato e lisciato (Screed to falls, lightweight expanded clay concrete)", "m2", 1_950.0, 17.80, {"voci": "E.01.010.a"}),
                ("E.2", "Impermeabilizzazione della copertura con doppia membrana bitume polimero elastomerica 4+4 mm, strato superiore ardesiato, compresi risvolti e raccordi (Two-layer elastomeric bituminous roof waterproofing)", "m2", 2_050.0, 27.50, {"voci": "E.01.030.b"}),
                ("E.3", "Isolamento termico della copertura in polistirene estruso XPS dello spessore di 120 mm, posato a secco sotto pavimento galleggiante (Roof thermal insulation, XPS 120 mm)", "m2", 1_950.0, 24.80, {"voci": "E.02.010.a"}),
                ("E.4", "Impermeabilizzazione delle strutture controterra con membrana bituminosa e protezione con lastra bugnata in HDPE, compreso drenaggio al piede (Below-grade tanking with HDPE protection board)", "m2", 2_850.0, 31.00, {"voci": "E.02.030.a"}),
                ("E.5", "Isolamento a cappotto esterno in EPS con grafite dello spessore di 140 mm, compresi rasatura armata con rete in fibra di vetro e finitura ai silicati (External wall insulation, graphite EPS 140 mm, silicate render)", "m2", 6_150.0, 62.00, {"voci": "E.03.010.b"}),
                ("E.6", "Rivestimento di facciata in gres porcellanato su sottostruttura ventilata in alluminio, alle zoccolature e ai fronti delle logge (Ventilated porcelain rainscreen to plinths and loggias)", "m2", 1_450.0, 148.00, {"voci": "E.03.030.a"}),
                ("E.7", "Serramenti esterni in PVC-alluminio a taglio termico con vetrocamera basso emissivo, trasmittanza Uw non superiore a 1,3 W/m2K, compresi controtelai, ferramenta e posa in opera qualificata (External windows, thermally broken, Uw <= 1.3 W/m2K)", "m2", 3_250.0, 398.00, {"voci": "E.04.010.c"}),
                ("E.8", "Oscuramenti con avvolgibili in alluminio coibentato e cassonetti isolati conformi ai requisiti acustici passivi (Insulated aluminium roller shutters and acoustic boxes)", "m2", 2_650.0, 118.00, {"voci": "E.04.030.a"}),
                ("E.9", "Opere da lattoniere: scossaline, converse, canali di gronda e pluviali in lamiera di alluminio preverniciato (Sheet metal flashings, gutters and downpipes)", "m", 1_850.0, 32.50, {"voci": "E.05.010.a"}),
                ("E.10", "Sistemi anticaduta permanenti di copertura: linee vita, ganci di sicurezza e punti di ancoraggio certificati per la manutenzione (Permanent roof fall arrest lines, hooks and certified anchor points)", "m", 380.0, 68.00, {"voci": "E.05.030.a"}),
                ("E.11", "Soglie, davanzali e copertine in pietra ricomposta per finestre, logge e parapetti, compresi gocciolatoio e sigillature (Reconstituted stone sills, thresholds and copings with drip and sealant)", "m", 2_150.0, 46.50, {"voci": "E.06.010.b"}),
            ],
        ),
        (
            "F",
            "Cap. F - Finiture interne e opere di completamento (Internal finishes)",
            {"voci": "F"},
            [
                ("F.1", "Intonaco premiscelato a base gesso applicato a macchina su pareti e soffitti interni, compresi paraspigoli e rifiniture (Machine-applied gypsum plaster to walls and ceilings)", "m2", 46_000.0, 14.60, {"voci": "F.01.010.a"}),
                ("F.2", "Massetto per pavimenti in sabbia e cemento alleggerito dello spessore di 8 cm, compreso materassino anticalpestio con risvolti perimetrali (Floor screed 80 mm with acoustic resilient layer)", "m2", 13_600.0, 22.50, {"voci": "F.01.030.b"}),
                ("F.3", "Pavimento in gres porcellanato formato 60x60 cm posato con collante cementizio, compresi fugatura e battiscopa (Porcelain floor tiling 600x600 with skirting)", "m2", 11_200.0, 48.50, {"voci": "F.02.010.a"}),
                ("F.4", "Rivestimento in gres porcellanato per bagni e cucine fino a 2,20 m di altezza, compresi pezzi speciali (Porcelain wall tiling to bathrooms and kitchens)", "m2", 5_400.0, 45.50, {"voci": "F.02.030.b"}),
                ("F.5", "Tinteggiatura con idropittura traspirante a due mani su fondo fissativo, su pareti e soffitti (Two-coat breathable emulsion on primer)", "m2", 44_000.0, 7.60, {"voci": "F.03.010.a"}),
                ("F.6", "Porte interne tamburate rivestite in laminato, compresi telaio, coprifili, ferramenta e maniglieria (Internal flush doors, laminate faced, complete)", "cad", 480.0, 298.00, {"voci": "F.04.010.c"}),
                ("F.7", "Portoncini blindati di ingresso agli alloggi in classe antieffrazione 3, compresi pannello di rivestimento e serratura di sicurezza (Armoured flat entrance doors, burglary class 3)", "cad", 96.0, 985.00, {"voci": "F.04.030.a"}),
                ("F.8", "Controsoffitti in lastre di gesso rivestito su orditura metallica nei bagni e nei disimpegni, comprese botole di ispezione (Plasterboard ceilings with access hatches)", "m2", 4_800.0, 30.50, {"voci": "F.05.010.b"}),
                ("F.9", "Pavimento in listoni di legno prefinito di rovere posato flottante su materassino acustico nelle zone giorno e notte degli alloggi (Engineered oak plank flooring, floating on acoustic underlay)", "m2", 4_200.0, 62.00, {"voci": "F.02.050.a"}),
                ("F.10", "Opere da fabbro interne: parapetti dei vani scala, corrimano e ringhiere delle logge in acciaio zincato e verniciato a polveri (Internal metalwork, stair balustrades, handrails and loggia railings)", "m", 1_180.0, 128.00, {"voci": "F.06.010.a"}),
                ("F.11", "Finiture degli atri di ingresso: cassette postali, segnaletica dei piani, numeri civici, zerbini a incasso e specchiature (Entrance hall fit-out, letterboxes, floor signage, matwells and mirrors)", "a corpo", 1.0, 68_000.00, {"voci": "F.06.030.b"}),
            ],
        ),
        (
            "G",
            "Cap. G - Impianti idrico-sanitari, di climatizzazione e ventilazione (Plumbing, heating and ventilation)",
            {"voci": "G"},
            [
                ("G.1", "Rete di adduzione idrica in tubo multistrato con collettori di distribuzione e contabilizzazione per singolo alloggio (Domestic water distribution, multilayer pipe and manifolds, per flat)", "cad", 96.0, 1_480.00, {"voci": "G.01.010.a"}),
                ("G.2", "Rete di scarico in polipropilene fonoassorbente, comprese colonne, braghe, ventilazione primaria e collettori di sub-irrigazione (Acoustic polypropylene drainage, stacks and branches)", "m", 4_200.0, 26.50, {"voci": "G.01.030.b"}),
                ("G.3", "Apparecchi sanitari sospesi in vitreous china con cassetta a incasso e rubinetteria monocomando, compresi accessori (Wall-hung sanitaryware with concealed cistern and mixer taps)", "cad", 610.0, 448.00, {"voci": "G.02.010.a"}),
                ("G.4", "Impianto di riscaldamento e raffrescamento a pannelli radianti a pavimento con collettori, termoregolazione per ambiente e cronotermostati (Underfloor heating and cooling with zone control)", "m2", 10_400.0, 53.50, {"voci": "G.03.010.c"}),
                ("G.5", "Pompa di calore aria-acqua ad alta efficienza da 12 kW per singolo alloggio, compreso accumulo per acqua calda sanitaria da 200 litri (Air to water heat pump 12 kW with 200 l DHW cylinder, per flat)", "cad", 96.0, 5_480.00, {"voci": "G.03.030.a"}),
                ("G.6", "Impianto di ventilazione meccanica controllata a doppio flusso con recuperatore di calore ad alta efficienza, per singolo alloggio (Balanced mechanical ventilation with heat recovery, per flat)", "cad", 96.0, 1_920.00, {"voci": "G.04.010.b"}),
                ("G.7", "Impianto di ventilazione ed estrazione fumi dell'autorimessa interrata, comprese condotte, ventilatori di emergenza e serrande tagliafuoco (Basement car park ventilation and smoke extract)", "a corpo", 1.0, 168_000.00, {"voci": "G.04.030.a"}),
                ("G.8", "Centrale idrica con gruppo di pressurizzazione, riserva idrica, contabilizzazione condominiale e allaccio all'acquedotto (Water plant room, booster set, storage and mains connection)", "a corpo", 1.0, 96_000.00, {"voci": "G.05.010.a"}),
                ("G.9", "Stazione di sollevamento delle acque reflue dei piani interrati con doppia elettropompa, valvola di non ritorno e quadro di comando (Basement foul water pumping station, duty and standby pumps, non-return valve and control panel)", "a corpo", 1.0, 46_000.00, {"voci": "G.01.050.a"}),
                ("G.10", "Coibentazione delle tubazioni idroniche e delle canalizzazioni aerauliche con spessori conformi all'allegato B del DPR 412/1993 (Thermal insulation to hydronic pipework and ductwork per DPR 412/1993 Annex B)", "m", 5_600.0, 14.50, {"voci": "G.03.050.b"}),
                ("G.11", "Collaudi funzionali, bilanciamento dei circuiti, disinfezione delle reti idriche e rilascio delle dichiarazioni di conformità ai sensi del DM 37/2008 (Commissioning, balancing, water system disinfection and DM 37/2008 conformity declarations)", "a corpo", 1.0, 58_000.00, {"voci": "G.06.010.a"}),
            ],
        ),
        (
            "H",
            "Cap. H - Impianti elettrici, speciali, antincendio ed elevatori (Electrical, ELV, fire systems and lifts)",
            {"voci": "H"},
            [
                ("H.1", "Impianto elettrico di alloggio realizzato al livello 2 secondo la norma CEI 64-8/3, compresi tubazioni sottotraccia, cavi, quadro di unita e apparecchi di comando (Flat electrical installation to CEI 64-8/3 level 2)", "cad", 96.0, 4_450.00, {"voci": "H.01.010.a"}),
                ("H.2", "Impianti elettrici delle parti comuni, montanti in cavedio, quadri di piano, illuminazione a LED e illuminazione di emergenza (Common area electrical installation, risers, boards and LED lighting)", "a corpo", 1.0, 268_000.00, {"voci": "H.01.030.b"}),
                ("H.3", "Impianto di terra, collegamenti equipotenziali e protezione contro le scariche atmosferiche secondo la norma CEI 81-10 (Earthing, bonding and lightning protection to CEI 81-10)", "a corpo", 1.0, 64_000.00, {"voci": "H.02.010.a"}),
                ("H.4", "Impianto fotovoltaico in copertura con moduli in silicio monocristallino, inverter, accumulo elettrochimico e sistema di monitoraggio (Rooftop photovoltaic array with inverters, storage and monitoring)", "kWp", 80.0, 1_240.00, {"voci": "H.03.010.a"}),
                ("H.5", "Impianto videocitofonico digitale con controllo accessi e predisposizione della rete in fibra ottica per ciascuna unità immobiliare (Digital entry system, access control and fibre readiness, per flat)", "cad", 96.0, 428.00, {"voci": "H.03.030.a"}),
                ("H.6", "Impianto di rivelazione incendi e segnalazione ottico-acustica a servizio dell'autorimessa e dei locali tecnici (Fire detection and alarm to car park and plant rooms)", "a corpo", 1.0, 78_000.00, {"voci": "H.04.010.b"}),
                ("H.7", "Rete idranti e naspi UNI 45 dell'autorimessa con gruppo di pressurizzazione antincendio e attacco di mandata per i vigili del fuoco (Hydrant and hose reel system with fire pump set and brigade inlet)", "a corpo", 1.0, 132_000.00, {"voci": "H.04.030.a"}),
                ("H.8", "Ascensori elettrici senza locale macchine, portata 630 kg, 8 fermate, cabina accessibile secondo il DM 236/1989, compresi collaudo e messa in servizio (Machine room less lifts, 630 kg, 8 stops, accessible to DM 236/1989)", "cad", 3.0, 33_400.00, {"voci": "H.05.010.c"}),
                ("H.9", "Punti di ricarica per veicoli elettrici nell'autorimessa, colonnine da 7,4 kW, infrastruttura di canalizzazione e sistema di bilanciamento dei carichi (Electric vehicle charging points 7.4 kW with containment and load balancing)", "cad", 24.0, 1_180.00, {"voci": "H.03.050.a"}),
                ("H.10", "Illuminazione dell'autorimessa, delle cantine e dei percorsi esterni con apparecchi a LED, sensori di presenza e alimentazione di emergenza (LED lighting to car park, stores and external routes with presence detection)", "a corpo", 1.0, 86_000.00, {"voci": "H.01.050.b"}),
                ("H.11", "Impianto centralizzato di ricezione televisiva e satellitare con rete di distribuzione in fibra e amplificatori di piano (Centralised TV and satellite reception with fibre distribution and floor amplifiers)", "a corpo", 1.0, 42_000.00, {"voci": "H.03.070.a"}),
            ],
        ),
        (
            "I",
            "Cap. I - Opere esterne, urbanizzazioni e sistemazioni a verde (External works, services and landscaping)",
            {"voci": "I"},
            [
                ("I.1", "Pavimentazione carrabile in masselli autobloccanti in calcestruzzo dello spessore di 8 cm su sottofondo in misto granulare stabilizzato (Block paving 80 mm on granular sub-base)", "m2", 1_850.0, 33.50, {"voci": "I.01.010.a"}),
                ("I.2", "Pavimentazione delle rampe e dei percorsi carrabili in conglomerato bituminoso, strato di collegamento e tappeto di usura (Bituminous paving to ramps and driveways, binder and wearing course)", "m2", 1_250.0, 21.50, {"voci": "I.01.030.b"}),
                ("I.3", "Reti di sottoservizi esterne per fognatura nera e bianca, acquedotto, energia elettrica e telecomunicazioni, compresi pozzetti, chiusini e allacci alle reti pubbliche (External services, foul and surface drainage, water, power and telecoms)", "m", 620.0, 138.00, {"voci": "I.02.010.a"}),
                ("I.4", "Vasca di laminazione delle acque meteoriche e impianto di trattamento delle acque di prima pioggia, compresi pompe e quadro di comando (Stormwater attenuation tank and first flush treatment plant)", "a corpo", 1.0, 118_000.00, {"voci": "I.02.030.a"}),
                ("I.5", "Recinzione perimetrale con muretto in cemento armato e ringhiera metallica zincata e verniciata, compresi cancelli carrabili motorizzati (Perimeter wall, galvanised railing and motorised vehicle gates)", "m", 310.0, 168.00, {"voci": "I.03.010.b"}),
                ("I.6", "Sistemazione a verde con terreno vegetale, prato a rotoli, alberature di alto fusto, arbusti e impianto di irrigazione automatico (Soft landscaping, turf, trees, shrubs and automatic irrigation)", "m2", 2_400.0, 31.50, {"voci": "I.04.010.a"}),
                ("I.7", "Cordoli in calcestruzzo, caditoie e canalette di raccolta delle acque meteoriche delle aree esterne, compresi allacci alla rete bianca (Precast kerbs, gullies and channel drains with connections to the surface water system)", "m", 780.0, 58.00, {"voci": "I.01.050.a"}),
                ("I.8", "Arredo urbano e area gioco: panchine, cestini, rastrelliere per biciclette, giochi e pavimentazione antitrauma certificata (Site furniture and play area, benches, bins, cycle racks and certified safety surfacing)", "a corpo", 1.0, 78_000.00, {"voci": "I.04.030.b"}),
            ],
        ),
    ],
    # Italian price build-up. A prezzario price already contains spese generali
    # and utile d'impresa, so the rates above are direct cost and the two are
    # added here instead. Spese generali run on the direct cost at the
    # conventional rate inside the 13 to 17 per cent band; utile d'impresa is
    # taken at 10 per cent on the direct cost already loaded with spese
    # generali, which is the order the analisi dei prezzi uses and the reason
    # the two compound to 1.265 rather than adding to 1.25. Oneri della
    # sicurezza are quantified on the direct cost and are not subject to the
    # tender discount; like the line rates they are stated net of spese
    # generali and utile, which a real piano di sicurezza would carry inside
    # its own prices. IVA is the last line and runs on the cumulative amount.
    markups=[
        ("Spese generali 15 per cento (General overheads)", 15.0, "overhead", "direct_cost"),
        ("Utile d'impresa 10 per cento (Contractor's profit)", 10.0, "profit", "cumulative"),
        ("Oneri della sicurezza non soggetti a ribasso (Safety costs, not subject to discount)", 2.5, "other", "direct_cost"),
        ("IVA 10 per cento (VAT at 10 percent)", 10.0, "tax", "cumulative"),
    ],
    total_months=30,
    tender_name="Appalto generale opere edili e impianti (Main contract, building and services)",
    tender_companies=[
        ("Costruzioni Valmontino S.p.A.", "gare@valmontino.example", 0.97),
        ("Impresa Edile Certosa Nova S.r.l.", "appalti@certosanova.example", 1.03),
        ("Consorzio Edile Aurelia Ponente", "gare@aureliaponente.example", 1.01),
    ],
    tender_packages=[
        (
            "Strutture e fondazioni speciali (Structure and special foundations)",
            "Scavi, berlinese di micropali, pali trivellati, platea, strutture in cemento armato e solai. Categoria OG1, qualificazione SOA richiesta.",
            "evaluating",
            [
                ("Costruzioni Valmontino S.p.A.", "gare@valmontino.example", 0.97),
                ("Impresa Edile Certosa Nova S.r.l.", "appalti@certosanova.example", 1.03),
                ("Fondazioni Aniene Opere S.r.l.", "preventivi@anieneopere.example", 1.01),
            ],
        ),
        (
            "Involucro edilizio e serramenti (Building envelope and windows)",
            "Cappotto termico, facciata ventilata, impermeabilizzazioni, serramenti esterni, oscuramenti e opere da lattoniere.",
            "issued",
            [
                ("Serramenti Vallelunga S.r.l.", "preventivi@vallelunga.example", 0.98),
                ("Facciate Ostiense Group S.r.l.", "gare@facciateostiense.example", 1.05),
                ("Involucri Portuense S.r.l.", "appalti@involucriportuense.example", 1.02),
            ],
        ),
        (
            "Impianti meccanici ed elettrici (Mechanical and electrical installations)",
            "Impianti idrico-sanitari, pannelli radianti, pompe di calore, ventilazione meccanica, impianti elettrici e speciali, antincendio ed elevatori. Categorie OS3, OS28, OS30 e OS4.",
            "collecting",
            [
                ("Termoidraulica Casaletto S.r.l.", "gare@casaletto.example", 0.99),
                ("Elettroimpianti Nomentana S.r.l.", "appalti@elettronomentana.example", 1.04),
                ("Impianti Salaria Tecnica S.r.l.", "gare@salariatecnica.example", 1.02),
            ],
        ),
        (
            "Finiture interne e opere esterne (Interior finishes and external works)",
            "Intonaci, massetti, pavimenti e rivestimenti, tinteggiature, porte interne, controsoffitti, pavimentazioni esterne e sistemazioni a verde.",
            "collecting",
            [
                ("Finiture Trastevere Opere S.r.l.", "preventivi@trastevereopere.example", 0.98),
                ("Verde e Strade Litoranea S.r.l.", "gare@litoranea.example", 1.03),
                ("Edilfiniture Prenestina S.r.l.", "appalti@edilprenestina.example", 1.01),
            ],
        ),
    ],
    schedule_activities=[
        ("Allestimento cantiere e opere provvisionali", "2026-03-02", "2026-04-30"),
        ("Scavi e movimenti terra", "2026-04-01", "2026-07-31"),
        ("Berlinese di micropali e pali di fondazione", "2026-05-01", "2026-08-31"),
        ("Platea, muri controterra e strutture interrate", "2026-08-01", "2026-12-31"),
        ("Strutture in elevazione e solai", "2026-12-01", "2027-08-31"),
        ("Murature, tamponamenti e divisori", "2027-04-01", "2027-11-30"),
        ("Coperture e impermeabilizzazioni", "2027-07-01", "2027-11-30"),
        ("Cappotto termico e facciata ventilata", "2027-08-01", "2028-02-29"),
        ("Serramenti esterni e oscuramenti", "2027-10-01", "2028-03-31"),
        ("Impianti meccanici, tracce e reti", "2027-06-01", "2028-04-30"),
        ("Impianti elettrici e speciali", "2027-07-01", "2028-05-31"),
        ("Finiture interne, pavimenti e rivestimenti", "2027-11-01", "2028-06-30"),
        ("Montaggio ascensori e collaudi impiantistici", "2028-02-01", "2028-06-30"),
        ("Opere esterne, urbanizzazioni e sistemazioni a verde", "2028-03-01", "2028-07-31"),
        ("Collaudo statico, agibilità e consegna", "2028-06-01", "2028-08-31"),
    ],
    project_metadata={
        "address": "Via di Mezzocammino 118, 00128 Roma, Italia",
        "client": "Immobiliare Mezzocammino Sviluppo S.r.l.",
        "architect": "Studio di Architettura Portuense Associati",
        "structural_engineer": "Studio di Ingegneria Strutturale Aniene",
        "quantity_surveyor": "Studio di computo metrico e contabilità dei lavori Lungotevere",
        "safety_coordinator": "Coordinatore per la sicurezza in progettazione ed esecuzione ai sensi del D.Lgs. 81/2008 Titolo IV",
        "gfa_m2": 17200,
        "gfa_above_ground_m2": 12800,
        "site_area_m2": 6800,
        "storeys": "7 piani fuori terra, 2 piani interrati (7 above ground, 2 basements)",
        "basement_levels": 2,
        "building_height_m": 22.4,
        "flats": 96,
        "stair_cores": 2,
        "parking_spaces": 152,
        "structure_system": "Telaio in cemento armato gettato in opera con nuclei di controvento, fondazione su pali trivellati e platea",
        "seismic_design": (
            "Zona sismica 3, classe d'uso II, vita nominale 50 anni, categoria di sottosuolo C, "
            "categoria topografica T1, classe di duttilità CD B ai sensi del DM 17/01/2018. "
            "I parametri di pericolosità del sito vanno ricalcolati sulle coordinate reali "
            "prima di qualsiasi verifica strutturale."
        ),
        "energy_performance": (
            "Edificio a energia quasi zero secondo il DM 26/06/2015, impianti interamente "
            "elettrici a pompa di calore, fotovoltaico in copertura dimensionato sul criterio "
            "dell'Allegato III del D.Lgs. 199/2021."
        ),
        "construction_standards": [
            "DM 17/01/2018 Norme Tecniche per le Costruzioni (NTC 2018)",
            "Circolare 21/01/2019 n. 7 C.S.LL.PP. Istruzioni per l'applicazione delle NTC 2018",
            "DPR 380/2001 Testo unico delle disposizioni in materia edilizia",
            "DM 26/06/2015 Requisiti minimi di prestazione energetica degli edifici",
            "D.Lgs. 199/2021 Quota di fonti rinnovabili negli edifici di nuova costruzione",
            "DPCM 05/12/1997 Requisiti acustici passivi degli edifici",
            "DM 236/1989 Accessibilità, visitabilità e adattabilità degli edifici",
            "DPR 151/2011 attività 75, autorimesse; DM 16/05/1987 n. 246 edifici di civile abitazione",
            "D.Lgs. 81/2008 Titolo IV Cantieri temporanei o mobili",
            "UNI 11337 Gestione digitale dei processi informativi delle costruzioni",
        ],
        "estimating_method": (
            "Computo metrico estimativo su elenco prezzi, redatto sul Prezzario Regionale delle "
            "Opere Pubbliche della Regione Lazio e integrato con analisi dei prezzi per le voci "
            "non presenti, secondo il criterio dell'art. 41 comma 13 del D.Lgs. 36/2023."
        ),
        "regulator": (
            "Sportello Unico per l'Edilizia di Roma Capitale per il permesso di costruire ex art. 10 "
            "DPR 380/2001; Regione Lazio, Area Genio Civile di Roma, per il deposito del progetto "
            "strutturale ex art. 65 DPR 380/2001; Comando Provinciale dei Vigili del Fuoco di Roma "
            "per l'autorimessa interrata."
        ),
        "price_level_note": (
            "Livello prezzi Roma 2026, IVA esclusa. I prezzi unitari sono costi diretti e non "
            "prezzi di prezzario: il prezzo di elenco si ottiene moltiplicando per 1,265."
        ),
        "markup_base_note": (
            "Le spese generali sono convenzionalmente comprese fra il 13 e il 17 per cento e sono "
            "calcolate sui costi diretti; l'utile d'impresa è pari al 10 per cento ed è calcolato "
            "sui costi diretti già comprensivi di spese generali. Le due incidenze si compongono in "
            "1,15 x 1,10 = 1,265, che è la quota già inclusa in un prezzo di prezzario e per questo "
            "scorporata dai prezzi unitari di questo computo."
        ),
        "vat_note": (
            "IVA al 10 per cento sulle prestazioni dipendenti da contratto di appalto per la "
            "costruzione di fabbricati residenziali non di lusso. L'aliquota scende al 4 per cento "
            "quando l'appalto riguarda una prima casa e sale al 22 per cento negli altri casi, "
            "quindi dipende dall'acquirente e non dall'edificio. I subappalti nel settore edile "
            "sono soggetti a inversione contabile e non espongono IVA."
        ),
        "labour_congruity_note": (
            "La verifica di congruità dell'incidenza della manodopera prevista dal DM 143/2021 si "
            "applica ai lavori edili e va calcolata sull'importo dei lavori con la percentuale "
            "prevista dall'allegato per la nuova edilizia civile, nell'edizione vigente alla data "
            "di denuncia del cantiere."
        ),
        "planning_note": (
            "Il contributo di costruzione e gli oneri di urbanizzazione primaria e secondaria ex "
            "art. 16 DPR 380/2001 non sono compresi nell'importo dei lavori. La dotazione minima di "
            "parcheggi pertinenziali segue il rapporto di 1 mq ogni 10 mc di costruzione previsto "
            "dalla legge 122/1989."
        ),
        "contract": (
            "Contratto di appalto a corpo ai sensi degli artt. 1655 e seguenti del codice civile, "
            "con computo metrico estimativo di riferimento e contabilità a misura per le varianti."
        ),
    },
    budget_boq_name="Quadro economico di controllo - Roma Mezzocammino (Control Budget)",
    planned_budget=20_800_000.0,
    actual_spend_ratio=0.38,
    spi_override=0.97,
    cpi_override=1.01,
    # The price list every line is cited from, so the Italian voce rules read
    # the list's own numbering as such. The codes illustrate that numbering;
    # they are not copied from the published list. The rates are direct cost,
    # net of the spese generali and utile carried as markups, which
    # rate_includes_overheads states so they are not taken as counted twice.
    # The quadro economico carries the same safety line as the bill: the costs
    # not subject to the tender discount stand apart in both.
    budget_markups=[
        ("Oneri della sicurezza non soggetti a ribasso (Safety costs, not subject to discount)", 2.5, "other", "direct_cost"),
    ],
    position_metadata={
        "prezzario": {
            "region": "Lazio",
            "region_code": "LAZ",
            "edition": "2026",
            "rate_includes_overheads": False,
            "list": "Prezzario Regionale delle Opere Pubbliche della Regione Lazio",
        }
    },
)
