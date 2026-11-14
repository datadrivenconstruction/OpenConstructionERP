# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate
from app.modules.boq.markup_templates import region_lines_for_country


def _french_markups() -> list[tuple[str, float, str, str]]:
    """The French markup stack as the demo template's (name, percent, category, apply_to) rows."""
    lines = region_lines_for_country("FR")
    if not lines:
        raise RuntimeError("the regional markup table has no French stack")
    return [
        (str(line["name"]), float(str(line["percentage"])), str(line["category"]), str(line["apply_to"]))
        for line in lines
    ]


# ---------------------------------------------------------------------------
# Flagship demo: Centre Hospitalier (acute-care hospital), Lyon (France)
# Standard: DPGF / fr / EUR - distinct healthcare archetype (vs school-paris,
# which is education).
#
# Program: New-build MCO acute-care hospital (medecine-chirurgie-obstetrique)
# on the Lyon Confluence health campus. 320 beds, 7 storeys above grade +
# 1 basement (logistics, technical plant, archives). GFA ~38 500 m2.
# Reinforced-concrete superstructure (Eurocode 2) with a seismic primary
# system designed to Eurocode 8 - Lyon is in seismic zone 3 (modere) per the
# French zonage sismique (decret 2010-1255). Building envelope to RE 2020
# tertiary thresholds; technical interstitial floors above the operating
# theatres and imaging suites. ISO 14644 clean rooms for the 9 operating
# theatres, EN ISO 7396-1 medical gas pipeline system, and NFC 15-211
# medical-grade electrical installation with 15 min / 120 min redundancy.
# Construction cost ~118 M EUR direct (Lyon Q2-2026 price level, hors taxes),
# ~157 M EUR with site overheads, general overheads, profit and risk
# (bénéfice et aléas), before TVA. Marche public de travaux allotis (loi MOP / CCAG-Travaux 2021).
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="hospital-lyon",
    project_name="Centre Hospitalier - Lyon Confluence",
    project_description=(
        "Construction neuve d'un centre hospitalier MCO (medecine, chirurgie, "
        "obstetrique) de 320 lits sur le campus sante de Lyon Confluence. "
        "7 niveaux hors sol + 1 sous-sol (logistique, locaux techniques, "
        "archives). Surface de plancher env. 38 500 m2. "
        "Structure en béton armé (Eurocode 2) avec système primaire "
        "parasismique calcule selon l'Eurocode 8 - Lyon en zone de sismicite "
        "3 (modere) au titre du zonage sismique francais (decret 2010-1255). "
        "Enveloppe conforme a la RE 2020 (seuils tertiaire) et aux exigences "
        "acoustiques NRA. Étages techniques interstitiels au-dessus des blocs "
        "operatoires et de l'imagerie. 9 salles d'operation en salle propre "
        "ISO 14644 classe ISO 5, distribution de fluides medicaux selon "
        "EN ISO 7396-1, installation électrique a usage medical NFC 15-211 "
        "avec redondance 15 min / 120 min et alimentation sans interruption. "
        "Protection radiologique des locaux d'imagerie (scanner, IRM, "
        "radiologie conventionnelle) selon NF C 15-160 et code de la sante "
        "publique. Sécurité incendie type U (etablissement de soins) selon "
        "le reglement ERP. Coût de construction env. 118 M EUR en coûts "
        "directs (~157 M EUR avec frais de chantier, frais généraux, benefice "
        "et aleas; niveau de prix Lyon 2026, hors taxes). Marche public de "
        "travaux allotis (loi MOP, CCAG-Travaux 2021)."
    ),
    region="FR",
    classification_standard="dpgf",
    currency="EUR",
    locale="fr",
    address={
        "street": "50 Quai Rambaud",
        "city": "Lyon",
        "postcode": "69002",
        "country": "France",
        "lat": 45.7406,
        "lng": 4.8161,
    },
    validation_rule_sets=["dpgf", "boq_quality"],
    boq_name="Estimation Détaillée - DPGF Centre Hospitalier",
    boq_description=(
        "Decomposition du prix global et forfaitaire (DPGF) par lots, "
        "phase PRO/DCE, pour le centre hospitalier de Lyon Confluence. "
        "Coûts directs en EUR, hors taxes."
    ),
    boq_metadata={
        "standard": "DPGF (France)",
        "phase": "PRO/DCE",
        "base_date": "2026-Q2",
        "price_level": "Lyon 2026",
    },
    sections=[
        # ── 01 Terrassement et Fondations (Earthworks & Foundations) ─────
        (
            "01",
            "Terrassement et Fondations",
            {"dpgf": "01"},
            [
                (
                    "01.1",
                    "Installation de chantier hopital en site contraint",
                    "lsum",
                    1,
                    685000.00,
                    {"dpgf": "01"},
                ),
                (
                    "01.2",
                    "Démolition existant et desamiantage",
                    "lsum",
                    1,
                    420000.00,
                    {"dpgf": "01"},
                ),
                ("01.3", "Terrassement general en deblai", "m3", 62000, 18.50, {"dpgf": "01"}),
                (
                    "01.4",
                    "Paroi moulee soutenement sous-sol",
                    "m2",
                    4800,
                    295.00,
                    {"dpgf": "01"},
                ),
                ("01.5", "Pieux fores béton armé d=800mm", "m", 5400, 165.00, {"dpgf": "01"}),
                ("01.6", "Rabattement de nappe phreatique", "lsum", 1, 245000.00, {"dpgf": "01"}),
                (
                    "01.7",
                    "Radier general béton armé C30/37 ep. 700mm",
                    "m3",
                    4350,
                    285.00,
                    {"dpgf": "01"},
                ),
                (
                    "01.8",
                    "Semelles, massifs et longrines béton armé",
                    "m3",
                    1850,
                    295.00,
                    {"dpgf": "01"},
                ),
                ("01.9", "Étanchéité cuvelage sous-sol type C", "m2", 9800, 52.00, {"dpgf": "01"}),
                (
                    "01.10",
                    "Remblaiement, compactage et évacuation des terres",
                    "m3",
                    48000,
                    24.00,
                    {"dpgf": "01"},
                ),
            ],
        ),
        # ── 02 Gros Oeuvre / Structure Beton (Concrete Superstructure) ───
        (
            "02",
            "Gros Oeuvre / Structure Béton",
            {"dpgf": "02"},
            [
                (
                    "02.1",
                    "Voiles béton armé C35/45 contreventement",
                    "m3",
                    8600,
                    345.00,
                    {"dpgf": "02"},
                ),
                ("02.2", "Poteaux béton armé C40/50", "m3", 2400, 425.00, {"dpgf": "02"}),
                ("02.3", "Planchers-dalles béton armé C30/37", "m3", 11200, 295.00, {"dpgf": "02"}),
                (
                    "02.4",
                    "Planchers techniques interstitiels surcharges",
                    "m3",
                    1850,
                    320.00,
                    {"dpgf": "02"},
                ),
                ("02.5", "Noyaux ascenseurs et escaliers C40/50", "m3", 3200, 410.00, {"dpgf": "02"}),
                ("02.6", "Poutres et longrines béton armé", "m3", 2100, 350.00, {"dpgf": "02"}),
                (
                    "02.7",
                    "Coffrage voiles, noyaux et planchers",
                    "m2",
                    132000,
                    54.00,
                    {"dpgf": "02"},
                ),
                (
                    "02.8",
                    "Armatures HA Fe E500 faconnees posees",
                    "t",
                    6400,
                    1850.00,
                    {"dpgf": "02"},
                ),
                (
                    "02.9",
                    "Appuis et joints parasismiques Eurocode 8",
                    "m",
                    480,
                    285.00,
                    {"dpgf": "02"},
                ),
                (
                    "02.10",
                    "Maçonnerie agglomere béton et reservations techniques",
                    "m2",
                    7800,
                    115.00,
                    {"dpgf": "02"},
                ),
            ],
        ),
        # ── 03 Charpente et Couverture (Roof Structure & Roofing) ────────
        (
            "03",
            "Charpente et Couverture",
            {"dpgf": "03"},
            [
                (
                    "03.1",
                    "Charpente métallique heliport et plant rooms",
                    "t",
                    285,
                    4600.00,
                    {"dpgf": "03"},
                ),
                ("03.2", "Bac acier support de couverture", "m2", 6800, 42.00, {"dpgf": "03"}),
                ("03.3", "Pare-vapeur toiture", "m2", 6800, 8.50, {"dpgf": "03"}),
                ("03.4", "Isolation thermique toiture PIR 200mm", "m2", 6800, 56.00, {"dpgf": "03"}),
                (
                    "03.5",
                    "Étanchéité membrane bi-couche autoprotegee",
                    "m2",
                    6800,
                    62.00,
                    {"dpgf": "03"},
                ),
                ("03.6", "Toiture vegetalisee extensive", "m2", 1400, 105.00, {"dpgf": "03"}),
                (
                    "03.7",
                    "Heliport en toiture structure et balisage",
                    "lsum",
                    1,
                    685000.00,
                    {"dpgf": "03"},
                ),
                ("03.8", "Lanterneaux de desenfumage", "pcs", 36, 2850.00, {"dpgf": "03"}),
                (
                    "03.9",
                    "Releves, solins et évacuation eaux pluviales",
                    "m",
                    1850,
                    62.00,
                    {"dpgf": "03"},
                ),
            ],
        ),
        # ── 04 Facades et Menuiseries Exterieures (Envelope) ─────────────
        (
            "04",
            "Facades et Menuiseries Exterieures",
            {"dpgf": "04"},
            [
                (
                    "04.1",
                    "Mur-rideau aluminium VEC double peau",
                    "m2",
                    9200,
                    685.00,
                    {"dpgf": "04"},
                ),
                (
                    "04.2",
                    "Vetage isolation thermique exterieure",
                    "m2",
                    7600,
                    165.00,
                    {"dpgf": "04"},
                ),
                (
                    "04.3",
                    "Bardage panneaux composites ventiles",
                    "m2",
                    4200,
                    245.00,
                    {"dpgf": "04"},
                ),
                (
                    "04.4",
                    "Menuiseries aluminium a rupture de pont thermique",
                    "m2",
                    3800,
                    480.00,
                    {"dpgf": "04"},
                ),
                ("04.5", "Brise-soleil orientables", "m2", 2400, 215.00, {"dpgf": "04"}),
                (
                    "04.6",
                    "Portes d'entrée automatiques sas",
                    "pcs",
                    8,
                    18500.00,
                    {"dpgf": "04"},
                ),
                (
                    "04.7",
                    "Membrane d'étanchéité a l'air et isolation laine minerale",
                    "m2",
                    21000,
                    56.00,
                    {"dpgf": "04"},
                ),
                (
                    "04.8",
                    "Habillage acrotere et couronnement",
                    "m",
                    1850,
                    95.00,
                    {"dpgf": "04"},
                ),
            ],
        ),
        # ── 05 Cloisonnement et Doublages (Partitions & Linings) ─────────
        (
            "05",
            "Cloisonnement et Doublages",
            {"dpgf": "05"},
            [
                (
                    "05.1",
                    "Cloisons placo standard 98/48",
                    "m2",
                    42000,
                    48.00,
                    {"dpgf": "05"},
                ),
                ("05.2", "Cloisons coupe-feu EI 60 chambres", "m2", 18500, 72.00, {"dpgf": "05"}),
                (
                    "05.3",
                    "Cloisons acoustiques 60 dB locaux sensibles",
                    "m2",
                    9800,
                    88.00,
                    {"dpgf": "05"},
                ),
                (
                    "05.4",
                    "Cloisons plombees salles d'imagerie",
                    "m2",
                    1850,
                    385.00,
                    {"dpgf": "05"},
                ),
                (
                    "05.5",
                    "Doublages thermo-acoustiques et habillage gaines",
                    "m2",
                    24000,
                    46.00,
                    {"dpgf": "05"},
                ),
                (
                    "05.6",
                    "Cloisons modulaires blocs operatoires",
                    "m2",
                    3200,
                    295.00,
                    {"dpgf": "05"},
                ),
                (
                    "05.7",
                    "Cloisons vitrées coupe-feu circulations",
                    "m2",
                    2800,
                    320.00,
                    {"dpgf": "05"},
                ),
                (
                    "05.8",
                    "Protection chocs angles et lisses",
                    "m",
                    8600,
                    32.00,
                    {"dpgf": "05"},
                ),
            ],
        ),
        # ── 06 CVC - Chauffage Ventilation Climatisation (HVAC) ──────────
        (
            "06",
            "CVC - Chauffage Ventilation Climatisation",
            {"dpgf": "06"},
            [
                (
                    "06.1",
                    "Centrales de traitement d'air double flux",
                    "pcs",
                    14,
                    165000.00,
                    {"dpgf": "06"},
                ),
                (
                    "06.2",
                    "CTA blocs operatoires haute efficacite filtration",
                    "pcs",
                    9,
                    245000.00,
                    {"dpgf": "06"},
                ),
                (
                    "06.3",
                    "Groupes froids a condensation a eau 800 kW",
                    "pcs",
                    4,
                    285000.00,
                    {"dpgf": "06"},
                ),
                (
                    "06.4",
                    "Tours de refroidissement fermees",
                    "pcs",
                    4,
                    95000.00,
                    {"dpgf": "06"},
                ),
                (
                    "06.5",
                    "Chaufferie gaz a condensation et sous-station réseau de chaleur",
                    "lsum",
                    1,
                    549000.00,
                    {"dpgf": "06"},
                ),
                (
                    "06.6",
                    "Réseau de gaines aerauliques tôle galvanisée",
                    "kg",
                    168000,
                    12.50,
                    {"dpgf": "06"},
                ),
                (
                    "06.7",
                    "Tuyauterie hydraulique acier calorifugee",
                    "m",
                    9800,
                    95.00,
                    {"dpgf": "06"},
                ),
                (
                    "06.8",
                    "Plafonds filtrants flux laminaire bloc operatoire",
                    "pcs",
                    9,
                    78000.00,
                    {"dpgf": "06"},
                ),
                (
                    "06.9",
                    "Caissons filtration HEPA H14",
                    "pcs",
                    480,
                    1850.00,
                    {"dpgf": "06"},
                ),
                (
                    "06.10",
                    "Diffuseurs, grilles et clapets coupe-feu/coupe-fumée",
                    "pcs",
                    4200,
                    215.00,
                    {"dpgf": "06"},
                ),
                ("06.11", "GTB / régulation et supervision", "lsum", 1, 1250000.00, {"dpgf": "06"}),
                (
                    "06.12",
                    "Équilibrage aeraulique et mise en service",
                    "lsum",
                    1,
                    285000.00,
                    {"dpgf": "06"},
                ),
            ],
        ),
        # ── 07 Fluides Medicaux (Medical Gas Systems) ────────────────────
        (
            "07",
            "Fluides Medicaux",
            {"dpgf": "07"},
            [
                (
                    "07.1",
                    "Centrale oxygene liquide et secours",
                    "lsum",
                    1,
                    385000.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.2",
                    "Centrale air medical comprime redondante",
                    "lsum",
                    1,
                    245000.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.3",
                    "Centrale vide medical et SEGA",
                    "lsum",
                    1,
                    215000.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.4",
                    "Réseau cuivre fluides medicaux degraisse",
                    "m",
                    12500,
                    78.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.5",
                    "Prises murales fluides medicaux normalisées",
                    "pcs",
                    2400,
                    185.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.6",
                    "Bras et poutres techniques de soins",
                    "pcs",
                    96,
                    18500.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.7",
                    "Coffrets de detente et de coupure de zone",
                    "pcs",
                    120,
                    2850.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.8",
                    "Centrale de surveillance et alarmes fluides",
                    "lsum",
                    1,
                    165000.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.9",
                    "Distribution protoxyde d'azote et CO2",
                    "m",
                    2800,
                    72.00,
                    {"dpgf": "07"},
                ),
                (
                    "07.10",
                    "Essais, certification et reception fluides",
                    "lsum",
                    1,
                    95000.00,
                    {"dpgf": "07"},
                ),
            ],
        ),
        # ── 08 Plomberie et Sanitaire (Plumbing & Sanitary) ──────────────
        (
            "08",
            "Plomberie et Sanitaire",
            {"dpgf": "08"},
            [
                (
                    "08.1",
                    "Réseau évacuation EU/EV fonte et PVC",
                    "m",
                    8600,
                    72.00,
                    {"dpgf": "08"},
                ),
                (
                    "08.2",
                    "Réseau alimentation eau froide/chaude multicouche",
                    "m",
                    11200,
                    58.00,
                    {"dpgf": "08"},
                ),
                (
                    "08.3",
                    "Traitement legionelle et bouclage ECS",
                    "lsum",
                    1,
                    245000.00,
                    {"dpgf": "08"},
                ),
                (
                    "08.4",
                    "Production ECS solaire thermique + ballons",
                    "lsum",
                    1,
                    185000.00,
                    {"dpgf": "08"},
                ),
                (
                    "08.5",
                    "Appareils sanitaires hospitaliers complets",
                    "pcs",
                    1850,
                    1250.00,
                    {"dpgf": "08"},
                ),
                (
                    "08.6",
                    "Robinetterie electronique et hygiene",
                    "pcs",
                    1450,
                    385.00,
                    {"dpgf": "08"},
                ),
                (
                    "08.7",
                    "Vidoirs et appareils de service",
                    "pcs",
                    220,
                    1850.00,
                    {"dpgf": "08"},
                ),
                (
                    "08.8",
                    "Neutralisation effluents laboratoires",
                    "lsum",
                    1,
                    145000.00,
                    {"dpgf": "08"},
                ),
            ],
        ),
        # ── 09 Electricite CFO/CFA et Securite (Electrical / IT / Safety) ─
        (
            "09",
            "Électricité CFO/CFA et Sécurité",
            {"dpgf": "09"},
            [
                (
                    "09.1",
                    "Poste de livraison HTA et transformateurs",
                    "lsum",
                    1,
                    685000.00,
                    {"dpgf": "09"},
                ),
                (
                    "09.2",
                    "Groupes electrogenes 2000 kVA redondants",
                    "pcs",
                    3,
                    385000.00,
                    {"dpgf": "09"},
                ),
                ("09.3", "Onduleurs ASI medicaux 15 min", "pcs", 12, 65000.00, {"dpgf": "09"}),
                (
                    "09.4",
                    "Transformateurs d'isolement medical IT",
                    "pcs",
                    120,
                    4200.00,
                    {"dpgf": "09"},
                ),
                (
                    "09.5",
                    "TGBT et tableaux divisionnaires",
                    "pcs",
                    85,
                    8500.00,
                    {"dpgf": "09"},
                ),
                (
                    "09.6",
                    "Chemins de câbles, câblage force et liaisons equipotentielles",
                    "m",
                    185000,
                    10.80,
                    {"dpgf": "09"},
                ),
                (
                    "09.7",
                    "Luminaires LED dont salles de soins",
                    "pcs",
                    14500,
                    165.00,
                    {"dpgf": "09"},
                ),
                (
                    "09.8",
                    "Éclairage operatoire scialytique",
                    "pcs",
                    18,
                    28500.00,
                    {"dpgf": "09"},
                ),
                ("09.9", "Éclairage de sécurité BAES", "pcs", 2200, 145.00, {"dpgf": "09"}),
                (
                    "09.10",
                    "SSI catégorie A type U et desenfumage",
                    "lsum",
                    1,
                    1070000.00,
                    {"dpgf": "09"},
                ),
                ("09.11", "Câblage VDI catégorie 6A", "m", 145000, 4.80, {"dpgf": "09"}),
                (
                    "09.12",
                    "Appel malade et signalisation chambres",
                    "pcs",
                    320,
                    2850.00,
                    {"dpgf": "09"},
                ),
                (
                    "09.13",
                    "Contrôle d'accès, videosurveillance et GTC sécurité",
                    "lsum",
                    1,
                    685000.00,
                    {"dpgf": "09"},
                ),
            ],
        ),
        # ── 10 Equipements Medicaux et Locaux Techniques (Medical Fit-out) ─
        (
            "10",
            "Équipements Medicaux et Locaux Techniques",
            {"dpgf": "10"},
            [
                (
                    "10.1",
                    "Salles propres blocs operatoires ISO 5",
                    "pcs",
                    9,
                    285000.00,
                    {"dpgf": "10"},
                ),
                (
                    "10.2",
                    "Protection plombee salle scanner",
                    "lsum",
                    1,
                    165000.00,
                    {"dpgf": "10"},
                ),
                (
                    "10.3",
                    "Cage de Faraday et blindage IRM",
                    "lsum",
                    1,
                    385000.00,
                    {"dpgf": "10"},
                ),
                (
                    "10.4",
                    "Protection radiologique radiologie conventionnelle",
                    "pcs",
                    6,
                    65000.00,
                    {"dpgf": "10"},
                ),
                (
                    "10.5",
                    "Portes plombees automatiques imagerie",
                    "pcs",
                    14,
                    18500.00,
                    {"dpgf": "10"},
                ),
                (
                    "10.6",
                    "Sterilisation centrale laveurs et autoclaves",
                    "lsum",
                    1,
                    685000.00,
                    {"dpgf": "10"},
                ),
                (
                    "10.7",
                    "Chambres mortuaires et cellules refrigerees",
                    "lsum",
                    1,
                    245000.00,
                    {"dpgf": "10"},
                ),
                (
                    "10.8",
                    "Chambres a flux d'air contrôle isolement",
                    "pcs",
                    24,
                    38500.00,
                    {"dpgf": "10"},
                ),
                (
                    "10.9",
                    "Tables d'operation et équipement de bloc",
                    "pcs",
                    9,
                    95000.00,
                    {"dpgf": "10"},
                ),
                (
                    "10.10",
                    "Pneumatique de transport echantillons",
                    "lsum",
                    1,
                    385000.00,
                    {"dpgf": "10"},
                ),
                (
                    "10.11",
                    "Chambre froide pharmacie et stockage",
                    "pcs",
                    6,
                    28500.00,
                    {"dpgf": "10"},
                ),
            ],
        ),
        # ── 11 Revetements et Finitions (Floor/Wall Finishes & Joinery) ──
        (
            "11",
            "Revetements et Finitions",
            {"dpgf": "11"},
            [
                (
                    "11.1",
                    "Chape liquide anhydrite et sol PVC hospitalier soudé",
                    "m2",
                    28500,
                    82.00,
                    {"dpgf": "11"},
                ),
                (
                    "11.2",
                    "Sol conducteur blocs operatoires",
                    "m2",
                    2400,
                    95.00,
                    {"dpgf": "11"},
                ),
                (
                    "11.3",
                    "Carrelage gres cerame locaux humides",
                    "m2",
                    6800,
                    88.00,
                    {"dpgf": "11"},
                ),
                (
                    "11.4",
                    "Revetement mural lessivable hygienique",
                    "m2",
                    18500,
                    62.00,
                    {"dpgf": "11"},
                ),
                (
                    "11.5",
                    "Faux plafonds demontables hydrofuges",
                    "m2",
                    24000,
                    52.00,
                    {"dpgf": "11"},
                ),
                (
                    "11.6",
                    "Faux plafonds coupe-feu et étanches bloc",
                    "m2",
                    4200,
                    145.00,
                    {"dpgf": "11"},
                ),
                ("11.7", "Peinture acrylique lessivable", "m2", 96000, 12.50, {"dpgf": "11"}),
                (
                    "11.8",
                    "Menuiseries intérieures portes hospitalieres",
                    "pcs",
                    2400,
                    1250.00,
                    {"dpgf": "11"},
                ),
                ("11.9", "Portes coupe-feu EI 60/EI 30", "pcs", 980, 1850.00, {"dpgf": "11"}),
                (
                    "11.10",
                    "Signaletique directionnelle et reglementaire",
                    "lsum",
                    1,
                    285000.00,
                    {"dpgf": "11"},
                ),
                (
                    "11.11",
                    "Ascenseurs lits 2500 kg et monte-charges",
                    "pcs",
                    16,
                    185000.00,
                    {"dpgf": "11"},
                ),
            ],
        ),
        # ── 12 VRD et Amenagements Exterieurs (External Works & Landscape) ─
        (
            "12",
            "VRD et Amenagements Exterieurs",
            {"dpgf": "12"},
            [
                (
                    "12.1",
                    "Voirie lourde accès urgences et logistique",
                    "m2",
                    9800,
                    78.00,
                    {"dpgf": "12"},
                ),
                (
                    "12.2",
                    "Parvis et cheminements pietons béton desactive",
                    "m2",
                    6200,
                    95.00,
                    {"dpgf": "12"},
                ),
                (
                    "12.3",
                    "Réseaux humides EU/EP/AEP exterieurs",
                    "m",
                    3400,
                    165.00,
                    {"dpgf": "12"},
                ),
                (
                    "12.4",
                    "Bassin de rétention et régulation pluviale",
                    "lsum",
                    1,
                    385000.00,
                    {"dpgf": "12"},
                ),
                (
                    "12.5",
                    "Réseaux secs et raccordements concessionnaires",
                    "m",
                    2800,
                    95.00,
                    {"dpgf": "12"},
                ),
                (
                    "12.6",
                    "Helistation au sol balisage et clotures",
                    "lsum",
                    1,
                    245000.00,
                    {"dpgf": "12"},
                ),
                (
                    "12.7",
                    "Espaces verts therapeutiques et plantations",
                    "m2",
                    8500,
                    48.00,
                    {"dpgf": "12"},
                ),
                (
                    "12.8",
                    "Stationnement et bornes de recharge VE",
                    "lsum",
                    1,
                    685000.00,
                    {"dpgf": "12"},
                ),
                (
                    "12.9",
                    "Éclairage extérieur LED sur mats et cloture site",
                    "pcs",
                    145,
                    2200.00,
                    {"dpgf": "12"},
                ),
            ],
        ),
    ],
    # The French national stack, read from the one table that states it, so the
    # demo and a new French bill are priced the same way.
    markups=_french_markups(),
    total_months=32,
    tender_name="Lot Gros Oeuvre",
    tender_companies=[
        ("Maurenne Bâtiment Sud-Est", "appels@maurenne.example", 0.98),
        ("Ferlac Construction Rhone-Alpes", "marches@ferlac.example", 1.05),
        ("Ardevin Construction France", "offres@ardevin.example", 1.01),
        ("Doreval Constructions", "appels@doreval.example", 1.03),
        ("Aurel Brissonde", "marches@brissonde.example", 0.99),
    ],
    project_metadata={
        "address": "50 Quai Rambaud, 69002 Lyon",
        "client": "Hospices Civils de Lyon (HCL)",
        "architect": "Groupe Solane + Vaudris Life Designers",
        "structural_engineer": "Nerval Batiments",
        "mep_engineer": "Vergenis / Portec",
        "contract_form": "Marche public de travaux allotis (loi MOP, CCAG-Travaux 2021)",
        "sdp_m2": 38500,
        "beds": 320,
        "operating_theatres": 9,
        "storeys": 7,
        "basement_levels": 1,
        "structure_system": "Béton armé contrevente (Eurocode 2 / Eurocode 8)",
        "codes": [
            "Eurocode 2 (NF EN 1992) - structures en béton",
            "Eurocode 8 (NF EN 1998) - calcul parasismique, zone 3 (modere)",
            "Decret 2010-1255 - zonage sismique de la France",
            "RE 2020 - reglementation environnementale (tertiaire)",
            "EN ISO 7396-1 - systemes de distribution de gaz medicaux",
            "NF C 15-211 - installations electriques a usage medical",
            "NF C 15-160 - protection contre les rayonnements ionisants",
            "ISO 14644 - salles propres (blocs operatoires ISO 5)",
            "Reglement de sécurité incendie ERP - type U (etablissements de soins)",
        ],
        "permits": (
            "Permis de construire Ville de Lyon (ZAC Lyon Confluence); "
            "avis de la commission de sécurité ERP type U; autorisation "
            "ARS Auvergne-Rhone-Alpes; declaration ASN pour les installations "
            "de radiologie; dossier loi sur l'eau (bassin de rétention)."
        ),
        "sustainability": "Cible HQE Bâtiment Durable niveau Excellent; RE 2020 tertiaire",
        "seismic": "Eurocode 8 - Lyon zone de sismicite 3 (modere), catégorie d'importance IV",
        "taxes_note": (
            "TVA au taux normal de 20 % applicable en sus des coûts indiqués. "
            "Les positions sont exprimees en coûts directs hors taxes."
        ),
    },
    tender_packages=[
        (
            "Gros Oeuvre",
            "Terrassement, fondations profondes, béton armé parasismique, maçonnerie",
            "evaluating",
            [
                ("Maurenne Bâtiment Sud-Est", "appels@maurenne.example", 0.98),
                ("Ferlac Construction Rhone-Alpes", "marches@ferlac.example", 1.05),
                ("Aurel Brissonde", "marches@brissonde.example", 0.99),
            ],
        ),
        (
            "Enveloppe / Couverture",
            "Mur-rideau, ITE, bardage, menuiseries exterieures, étanchéité, heliport",
            "evaluating",
            [
                ("Trelanne Facades", "appels@trelanne.example", 0.97),
                ("Clanmere Facades France", "marches@clanmere.example", 1.04),
                ("Etanova (Groupe Tarvane)", "offres@etanova.example", 1.02),
            ],
        ),
        (
            "CVC et Fluides Medicaux",
            "Centrales de traitement d'air, salles propres, fluides medicaux EN ISO 7396-1, GTB",
            "evaluating",
            [
                ("Navelis Solutions", "appels@navelis.example", 0.99),
                ("Oxyverne Medical Systems", "marches@oxyverne.example", 1.06),
                ("Calorine", "offres@calorine.example", 1.03),
            ],
        ),
        (
            "Électricité CFO/CFA et Sécurité",
            "Poste HTA, groupes electrogenes, IT medical, SSI, desenfumage, appel malade, VDI",
            "evaluating",
            [
                ("Belcaris Sante (Ardevin Energies)", "appels@belcaris.example", 0.97),
                ("Roverval France", "marches@roverval-fr.example", 1.05),
                ("Ferlac Energie Systemes", "offres@ferlac-energie.example", 1.02),
            ],
        ),
        (
            "Équipements Medicaux et Salles Propres",
            "Blocs operatoires ISO 5, blindage imagerie, sterilisation, isolement",
            "evaluating",
            [
                ("Sterivane France", "appels@sterivane.example", 0.98),
                ("Corvista / Medilane", "marches@medilane.example", 1.04),
                ("Aseptane France", "offres@aseptane.example", 1.01),
            ],
        ),
        (
            "Second Oeuvre et Finitions",
            "Cloisons, doublages, revetements, faux plafonds, menuiseries, ascenseurs",
            "evaluating",
            [
                ("Valmery (Groupe Ardevin)", "appels@valmery.example", 0.98),
                ("Sorenne Lyon (Groupe Ardevin)", "marches@sorenne.example", 1.04),
                ("Verthuis (Groupe Ardevin)", "offres@verthuis.example", 1.01),
            ],
        ),
        (
            "VRD et Amenagements Exterieurs",
            "Voirie, réseaux humides et secs, bassin de rétention, espaces verts, helistation",
            "evaluating",
            [
                ("Tarvane Rhone-Alpes Auvergne", "appels@tarvane.example", 0.99),
                ("Routavia (Groupe Ardevin)", "marches@routavia.example", 1.06),
                ("Gaspard Reynol (Groupe Halvest)", "offres@reynol.example", 1.02),
            ],
        ),
    ],
    budget_boq_name="Centre Hospitalier Lyon Confluence - Budget de Contrôle",
    planned_budget=118_000_000,
    actual_spend_ratio=0.42,
    spi_override=0.96,
    cpi_override=1.02,
)
