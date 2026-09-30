# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: czechia-cz - Office Building, Prague Karlin
# ---------------------------------------------------------------------------
# Czech rozpocet structured by TSKP groups, mapped to DIN 276 for the
# product's classification resolution. Prices are CZK excluding 21% DPH.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-prague",
    project_name="Administrativni budova - Praha Karlin (Office Building, Prague Karlin)",
    project_description=(
        "Novostavba administrativni budovy v Praze Karline, 10 nadzemich podlazi "
        "a 2 podzemni podlazi s 90 parkovacimi misty. Celkova podlahova plocha "
        "cca 14 000 m2. Monoliticky zelezobeton, zakladani na vrtanych pilotech. "
        "Obvodovy plast: lehky obvodovy plast s trojitym zasklenim. Energeticka "
        "narocnost budovy trida B. New-build office in Prague Karlin, 10 storeys "
        "with 2 basements. GFA approx. 14,000 m2. RC frame with bored pile "
        "foundations. Priced at Prague 2026 levels in CZK excluding DPH."
    ),
    region="CZ",
    classification_standard="din276",
    currency="CZK",
    locale="cs",
    address={
        "street": "Thamova 18",
        "city": "Prague",
        "postcode": "186 00",
        "country": "Czech Republic",
        "lat": 50.0928,
        "lng": 14.4492,
    },
    validation_rule_sets=["din276", "boq_quality"],
    boq_name="Rozpocet - Administrativni budova Karlin (Budget)",
    boq_description=(
        "Polozkovity rozpocet podle tridy stavebni produkce (TSKP) pro "
        "administrativni budovu o 10 NP a 2 PP. Ceny na urovni Praha 2026 "
        "v CZK bez DPH. Itemised budget by TSKP classification for a "
        "10-storey office building, Prague 2026 levels in CZK excluding DPH."
    ),
    boq_metadata={
        "standard": "TSKP / DIN 276",
        "phase": "Rozpocet pro vyberove rizeni (Tender budget)",
        "base_date": "2026-Q1",
        "price_level": "Praha 2026 (CZK, bez DPH)",
    },
    sections=[
        (
            "310",
            "310 - Zemni prace a zakladani (Earthworks and foundations)",
            {"din276": "310"},
            [
                ("310.01", "Inzenyrsko-geologicky pruzkum (Geotechnical investigation)", "lsum", 1, 850000, {"din276": "311"}),
                ("310.02", "Vykop stavebni jamy (Bulk excavation)", "m3", 14000, 320, {"din276": "313"}),
                ("310.03", "Odvoz a ulozeni vytezku (Disposal off site)", "m3", 12000, 480, {"din276": "313"}),
                ("310.04", "Zapazkove steny (Shoring to excavation)", "m2", 2200, 4800, {"din276": "312"}),
                ("310.05", "Vrtane piloty prumer 600mm (Bored piles 600mm)", "m", 3200, 3850, {"din276": "322"}),
                ("310.06", "Hlavice pilot a zakladove pasy C30/37 (Pile caps and beams)", "m3", 920, 6800, {"din276": "324"}),
                ("310.07", "Zakladova deska C30/37 vodonepropustna (Raft slab watertight)", "m3", 780, 7200, {"din276": "324"}),
                ("310.08", "Vyztuze zakladu B500B (Reinforcement to foundations)", "t", 165, 34500, {"din276": "324"}),
                ("310.09", "Hydroizolace spodni stavby (Waterproofing)", "m2", 2600, 1180, {"din276": "325"}),
            ],
        ),
        (
            "330",
            "330 - Svisle konstrukce (Vertical structures)",
            {"din276": "330"},
            [
                ("330.01", "Zelezobeton sloupy C40/50 (RC columns)", "m3", 480, 9800, {"din276": "331"}),
                ("330.02", "Zelezobeton jadra C40/50 (RC core walls)", "m3", 1050, 9200, {"din276": "331"}),
                ("330.03", "Lehky obvodovy plast trojite zaskleni (Curtain wall triple glazed)", "m2", 5400, 16500, {"din276": "337"}),
                ("330.04", "Kamenovy obklad soklu (Stone cladding to podium)", "m2", 680, 6800, {"din276": "335"}),
                ("330.05", "Vstupni dvere hlinikove automaticke (Entrance doors automatic)", "pcs", 4, 185000, {"din276": "334"}),
                ("330.06", "Vnejsi zasticka protislunechi (External sun shading)", "m2", 2800, 3800, {"din276": "338"}),
            ],
        ),
        (
            "340",
            "340 - Vnitrni steny a pricky (Internal walls)",
            {"din276": "340"},
            [
                ("340.01", "Sadrokartonova pricka dvojite opasteni 100mm (Drywall partition)", "m2", 6800, 1450, {"din276": "342"}),
                ("340.02", "Pozarne odolna pricka REI 60/120 (Fire rated partition)", "m2", 1800, 3200, {"din276": "342"}),
                ("340.03", "Prosklena pricka kancelari (Glazed office partition)", "m2", 2600, 7800, {"din276": "342"}),
                ("340.04", "Vnitrni dvere drevene s kovanim (Internal timber doors)", "pcs", 185, 18500, {"din276": "344"}),
                ("340.05", "Pozarni dvere EI 30/60 (Fire doors)", "pcs", 68, 28500, {"din276": "344"}),
                ("340.06", "Obklady sten sanitarni prostory (Wall tiles WCs)", "m2", 1200, 1850, {"din276": "345"}),
                ("340.07", "Malba latexova 2 vrstvy (Emulsion paint 2 coats)", "m2", 16000, 195, {"din276": "345"}),
                ("340.08", "WC kabiny HPL (Toilet cubicles)", "pcs", 36, 22000, {"din276": "346"}),
            ],
        ),
        (
            "350",
            "350 - Vodorovne konstrukce (Horizontal structures)",
            {"din276": "350"},
            [
                ("350.01", "Zelezobeton stropni deska C35/45, 260mm (RC flat slab)", "m2", 12500, 2850, {"din276": "351"}),
                ("350.02", "Vyztuze stropen B500B (Slab reinforcement)", "t", 1250, 34500, {"din276": "351"}),
                ("350.03", "Bedneni stropen a sloupech (Formwork)", "m2", 26000, 850, {"din276": "351"}),
                ("350.04", "Zdvojene podlahy 150mm (Raised access floor)", "m2", 10500, 1950, {"din276": "352"}),
                ("350.05", "Kobercova dlazba kancelari (Carpet tile offices)", "m2", 8800, 1150, {"din276": "352"}),
                ("350.06", "Keramicka dlazba lobby (Porcelain tile lobby)", "m2", 1100, 3200, {"din276": "352"}),
                ("350.07", "Kazetovy podhled kovovy (Suspended metal ceiling)", "m2", 10500, 1580, {"din276": "353"}),
                ("350.08", "Sadrokartonovy podhled (Plasterboard ceiling)", "m2", 2600, 1250, {"din276": "353"}),
            ],
        ),
        (
            "360",
            "360 - Zastreseni (Roofs)",
            {"din276": "360"},
            [
                ("360.01", "Tepelna izolace strechy PIR 180mm (Roof insulation)", "m2", 1400, 1450, {"din276": "363"}),
                ("360.02", "Povlakova krytina TPO (Single ply roof membrane)", "m2", 1400, 1080, {"din276": "363"}),
                ("360.03", "Extenzivni zelena strecha (Extensive green roof)", "m2", 500, 1750, {"din276": "363"}),
                ("360.04", "Odvodneni a pojistne pretoky (Roof drainage)", "lsum", 1, 850000, {"din276": "362"}),
                ("360.05", "Fotovoltaika 50 kWp (PV array)", "lsum", 1, 1850000, {"din276": "362"}),
            ],
        ),
        (
            "410",
            "410 - Zdravotne technicke instalace (Plumbing)",
            {"din276": "410"},
            [
                ("410.01", "Kanalizace a zakladove rozvody (Drainage below ground)", "m", 1100, 1180, {"din276": "411"}),
                ("410.02", "Zarizovaci predmety kompletni (Sanitaryware complete)", "pcs", 110, 22000, {"din276": "412"}),
                ("410.03", "Vodovodni rozvody (Water supply pipework)", "m", 2200, 850, {"din276": "412"}),
            ],
        ),
        (
            "420",
            "420 - Vytapeni a vzduchotechnika (Heating and ventilation)",
            {"din276": "420"},
            [
                ("420.01", "Tepelne cerpadlo vzduch-voda 150 kW (Air source heat pump)", "lsum", 1, 3200000, {"din276": "421"}),
                ("420.02", "Podlahove topeni a chlazeni (Underfloor heating/cooling)", "m2", 10500, 1050, {"din276": "423"}),
                ("420.03", "Vzduchotechnicke jednotky s rekuperaci (AHU with heat recovery)", "pcs", 4, 1450000, {"din276": "431"}),
                ("420.04", "Vzduchotechnicke potrubi (Ductwork)", "m2", 4200, 1580, {"din276": "431"}),
            ],
        ),
        (
            "440",
            "440 - Silnoproude rozvody (Electrical)",
            {"din276": "440"},
            [
                ("440.01", "Hlavni rozvodna NN (Main LV switchboard)", "pcs", 1, 1450000, {"din276": "443"}),
                ("440.02", "Podlazni rozvodnice (Floor distribution boards)", "pcs", 12, 115000, {"din276": "443"}),
                ("440.03", "Nahradni zdroj 400 kVA (Standby generator)", "pcs", 1, 3200000, {"din276": "442"}),
                ("440.04", "LED osvetleni DALI (LED lighting)", "m2", 12500, 1280, {"din276": "445"}),
                ("440.05", "Elektricky pozarni system EPS (Fire detection)", "m2", 14000, 350, {"din276": "454"}),
                ("440.06", "Spinklerova instalace (Sprinkler)", "m2", 14000, 780, {"din276": "454"}),
                ("440.07", "Osobni vytahy 1600 kg, 12 stanic (Passenger lifts)", "pcs", 3, 3800000, {"din276": "461"}),
                ("440.08", "Nakladni vytah 2000 kg (Goods lift)", "pcs", 1, 4200000, {"din276": "461"}),
                ("440.09", "Strukturovana kabelaz Cat 6A (Structured cabling)", "m2", 10500, 620, {"din276": "456"}),
                ("440.10", "System MaR / BMS (Building management)", "lsum", 1, 4800000, {"din276": "481"}),
                ("440.11", "Pristupovy system a CCTV (Access control and CCTV)", "lsum", 1, 3200000, {"din276": "453"}),
                ("440.12", "EZS elektronicka zabezpecovaci (Intruder alarm)", "lsum", 1, 1250000, {"din276": "452"}),
                ("440.13", "Dobijeci stanice EV 11 kW (EV charging)", "pcs", 8, 55000, {"din276": "442"}),
                ("440.14", "Uvedeni do provozu a zkousky (Commissioning)", "lsum", 1, 2200000, {"din276": "485"}),
                ("440.15", "Zachycovani destove vody (Rainwater harvesting)", "lsum", 1, 950000, {"din276": "419"}),
                ("440.16", "Nouzove osvetleni (Emergency lighting)", "lsum", 1, 1450000, {"din276": "445"}),
                ("440.17", "Kourovody a detektory garaze (Car park smoke detection)", "m2", 2800, 285, {"din276": "454"}),
                ("440.18", "UPS pro serverovnu (UPS for server room)", "pcs", 1, 1850000, {"din276": "442"}),
                ("440.19", "Ochrana pred bleskem (Lightning protection)", "lsum", 1, 1450000, {"din276": "446"}),
            ],
        ),
        (
            "500",
            "500 - Venkovni upravy (External works)",
            {"din276": "500"},
            [
                ("500.01", "Zpevnene plochy a dlazdeni (Hard landscaping)", "m2", 1500, 2400, {"din276": "520"}),
                ("500.02", "Sadove upravy (Soft landscaping)", "m2", 1100, 1250, {"din276": "530"}),
                ("500.03", "Venkovni kanalizace (External drainage)", "lsum", 1, 2800000, {"din276": "541"}),
                ("500.04", "Venkovni osvetleni (External lighting)", "pcs", 22, 52000, {"din276": "550"}),
                ("500.05", "Stojan na kola 50 mist (Bicycle parking)", "pcs", 50, 6200, {"din276": "560"}),
            ],
        ),
    ],
    markups=[
        ("Vedlejsi rozpoctove naklady (Site overheads)", 10.0, "overhead", "direct_cost"),
        ("Rezijni naklady (Head office overheads)", 6.0, "overhead", "direct_cost"),
        ("Zisk (Profit)", 5.0, "profit", "direct_cost"),
        ("DPH 21%", 21.0, "tax", "cumulative"),
    ],
    total_months=26,
    tender_name="Generalni dodavka - Administrativni budova Karlin",
    tender_companies=[
        ("Stavitelstvi Novak a.s.", "nabidky@stavitelstvi-novak.example", 0.98),
        ("Bohemia Build s.r.o.", "tender@bohemia-build.example", 1.03),
        ("Pragostavby a.s.", "nabidky@pragostavby.example", 1.01),
    ],
    project_metadata={
        "address": "Thamova 18, 186 00 Praha 8 - Karlin",
        "client": "Karlin Development s.r.o.",
        "architect": "Ateliery Holesovice s.r.o.",
        "structural_engineer": "Statika Praha s.r.o.",
        "qs": "Rozpocty Vinohrady s.r.o.",
        "gfa_m2": 14000,
        "storeys_above": 10,
        "storeys_below": 2,
        "parking_spaces": 90,
        "energy_class": "B",
    },
    tender_packages=[
        (
            "Hruba stavba (Structure)",
            "Zakladani, zelezobeton, steny a stropy",
            "evaluating",
            [
                ("Stavitelstvi Novak a.s.", "nabidky@stavitelstvi-novak.example", 0.98),
                ("Bohemia Build s.r.o.", "tender@bohemia-build.example", 1.03),
                ("Pragostavby a.s.", "nabidky@pragostavby.example", 1.01),
            ],
        ),
        (
            "TZB (M&E Services)",
            "Vytapeni, VZT, elektro, vytahy, EPS",
            "issued",
            [
                ("Technika Smichov s.r.o.", "nabidky@technika-smichov.example", 0.99),
                ("Instalace Morava a.s.", "tender@instalace-morava.example", 1.04),
            ],
        ),
    ],
)
