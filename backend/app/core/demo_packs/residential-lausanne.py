# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: Residential building Lausanne (Romandie, Switzerland)
# Pack: switzerland-ch  ·  BKP / CFC classification, SIA 451 cost planning
# ---------------------------------------------------------------------------
# A residential estimate in Suisse romande follows the same BKP/CFC structure
# as in the Deutschschweiz, but the project context uses French terminology.
# BKP = CFC (Code des frais de construction) in French, published by the CRB.
#
# Rates are Lausanne/Vaud 2026 market estimates in CHF, net of MWST/TVA.
# Lausanne residential construction runs slightly below Zurich office levels
# but still well above neighbouring France and Germany.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-lausanne",
    project_name="Ensemble residentiel Les Terrasses du Flon - Lausanne",
    project_description=(
        "Construction d'un ensemble residentiel de 72 appartements repartis "
        "sur 3 immeubles, 6 etages hors sol + 1 etage en sous-sol destine au "
        "parking souterrain (48 places) et aux caves. Surface brute de plancher "
        "SBP environ 12.600 m2, dont environ 10.200 m2 hors sol et 2.400 m2 "
        "en sous-sol, sur une parcelle d'environ 5.200 m2. Structure a dalles "
        "plates en beton arme sur voiles et colonnes, fondation sur radier. "
        "Enveloppe conforme au Standard Minergie, facades crepi sur isolation "
        "peripherique, menuiseries bois-metal triple vitrage. "
        "Devis CFC/BKP selon SIA 451, phase 32 projet de construction, "
        "couts de construction CFC 2+3+4 environ CHF 38 millions hors TVA. "
        "New-build residential complex of 72 apartments in 3 buildings, "
        "6 above-ground storeys + 1 basement level with 48 parking spaces. "
        "Gross floor area approx. 12,600 m2. RC flat-slab structure, "
        "Minergie envelope. BKP/CFC cost estimate per SIA 451, phase 32, "
        "approx. CHF 38 million construction cost excl. VAT."
    ),
    region="DACH",
    # The registry stores an Austrian or Swiss project under DIN 276, so every
    # line also carries the DIN 276 group its section falls in; without it the
    # Validate button failed every line for a cost group it never carried.
    classification_standard="bkp",
    currency="CHF",
    locale="fr",
    address={
        "street": "Avenue du Flon 24",
        "city": "Lausanne",
        "postcode": "1003",
        "country": "Switzerland",
        "lat": 46.5218,
        "lng": 6.6327,
    },
    validation_rule_sets=["boq_quality"],
    boq_name="Devis CFC/BKP (SIA 451, Phase 32 Projet de construction)",
    boq_description=(
        "Devis selon SIA 451, classification CFC/BKP, "
        "phase 32 projet de construction. Accent sur CFC 2 batiment et "
        "CFC 3 equipements du batiment. Base de prix Lausanne/Vaud 2026."
    ),
    boq_metadata={
        "standard": "BKP/CFC (CRB) / SIA 451",
        "phase": "SIA 112 Phase 32, Projet de construction",
        "base_date": "2026-Q1",
        "price_level": "Lausanne/Vaud 2026",
    },
    sections=[
        # ── BKP 211 Fouille, blindage ──────────────────────────────
        (
            "211",
            "CFC 211 - Fouille, blindage",
            {"bkp": "211", "din276": "330"},
            [
                ("211.1", "Paroi berlinoise bois + pieux HEB, h=5m", "m2", 2100, 245.00, {"bkp": "211", "din276": "330"}),
                ("211.2", "Ancrage provisoire tirants precontraints", "pcs", 80, 1450.00, {"bkp": "211", "din276": "330"}),
                ("211.3", "Rabattement de nappe + pompage", "month", 8, 14500.00, {"bkp": "211", "din276": "330"}),
            ],
        ),
        # ── BKP 212 Terrassement ───────────────────────────────────
        (
            "212",
            "CFC 212 - Terrassement",
            {"bkp": "212", "din276": "330"},
            [
                ("212.1", "Excavation fouille en pleine masse, classe 3-5", "m3", 28000, 24.00, {"bkp": "212", "din276": "330"}),
                ("212.2", "Transport + mise en decharge materiaux", "m3", 26000, 42.00, {"bkp": "212", "din276": "330"}),
                ("212.3", "Planie fond de fouille + compactage", "m2", 2400, 7.50, {"bkp": "212", "din276": "330"}),
                ("212.4", "Piste de chantier grave naturelle", "m2", 800, 38.00, {"bkp": "212", "din276": "330"}),
            ],
        ),
        # ── BKP 213 Fondation ──────────────────────────────────────
        (
            "213",
            "CFC 213 - Fondation",
            {"bkp": "213", "din276": "330"},
            [
                ("213.1", "Beton de proprete C12/15", "m2", 2400, 16.50, {"bkp": "213", "din276": "330"}),
                ("213.2", "Radier beton arme C30/37 WU, ep. 60cm", "m3", 1440, 265.00, {"bkp": "213", "din276": "330"}),
                ("213.3", "Armature radier BSt 500", "t", 180, 2050.00, {"bkp": "213", "din276": "330"}),
                ("213.4", "Joints d'etancheite + bandes gonflantes", "m", 960, 48.00, {"bkp": "213", "din276": "330"}),
                ("213.5", "Cuvelage sous-sol / etancheite", "m2", 2400, 52.00, {"bkp": "213", "din276": "330"}),
                ("213.6", "Fosses d'ascenseur + puisards", "pcs", 3, 9800.00, {"bkp": "213", "din276": "330"}),
            ],
        ),
        # ── BKP 214 Gros oeuvre 1 (murs porteurs, colonnes) ───────
        (
            "214",
            "CFC 214 - Gros oeuvre 1, murs porteurs et colonnes",
            {"bkp": "214", "din276": "330"},
            [
                ("214.1", "Murs sous-sol beton arme C30/37, ep. 30cm", "m3", 720, 295.00, {"bkp": "214", "din276": "330"}),
                ("214.2", "Coffrage murs grande surface", "m2", 4800, 45.00, {"bkp": "214", "din276": "330"}),
                ("214.3", "Armature murs BSt 500", "t", 86, 2050.00, {"bkp": "214", "din276": "330"}),
                ("214.4", "Colonnes beton arme C35/45", "m3", 240, 480.00, {"bkp": "214", "din276": "330"}),
                ("214.5", "Voiles contreventement cages escalier/ascenseur", "m3", 680, 450.00, {"bkp": "214", "din276": "330"}),
                ("214.6", "Coffrage voiles coffrage grimpant", "m2", 3800, 52.00, {"bkp": "214", "din276": "330"}),
                ("214.7", "Armature voiles BSt 500", "t", 92, 2050.00, {"bkp": "214", "din276": "330"}),
                ("214.8", "Isolation peripherique XPS 180mm enterre", "m2", 2100, 62.00, {"bkp": "214", "din276": "330"}),
                ("214.9", "Etancheite exterieure MPC", "m2", 2100, 52.00, {"bkp": "214", "din276": "330"}),
            ],
        ),
        # ── BKP 215 Gros oeuvre 2 (dalles, escaliers) ─────────────
        (
            "215",
            "CFC 215 - Gros oeuvre 2, dalles et escaliers",
            {"bkp": "215", "din276": "330"},
            [
                ("215.1", "Dalle plate beton arme C30/37, ep. 26cm", "m3", 3276, 385.00, {"bkp": "215", "din276": "330"}),
                ("215.2", "Coffrage dalles tables", "m2", 12600, 38.00, {"bkp": "215", "din276": "330"}),
                ("215.3", "Armature dalles BSt 500", "t", 380, 2050.00, {"bkp": "215", "din276": "330"}),
                ("215.4", "Renforcement anti-poinconnement", "pcs", 180, 380.00, {"bkp": "215", "din276": "330"}),
                ("215.5", "Escaliers prefabriques beton arme", "pcs", 36, 5800.00, {"bkp": "215", "din276": "330"}),
                ("215.6", "Garde-corps escalier acier + verre", "m", 360, 345.00, {"bkp": "215", "din276": "330"}),
            ],
        ),
        # ── BKP 221 Fenetres, portes exterieures ──────────────────
        (
            "221",
            "CFC 221 - Fenetres et portes exterieures",
            {"bkp": "221", "din276": "330"},
            [
                ("221.1", "Fenetres bois-metal triple vitrage Uw 0,90", "m2", 3800, 680.00, {"bkp": "221", "din276": "330"}),
                ("221.2", "Portes-fenetres coulissantes balcon", "pcs", 144, 2850.00, {"bkp": "221", "din276": "330"}),
                ("221.3", "Portes d'entree immeuble aluminium", "pcs", 3, 8500.00, {"bkp": "221", "din276": "330"}),
                ("221.4", "Volets roulants motorises", "pcs", 420, 580.00, {"bkp": "221", "din276": "330"}),
                ("221.5", "Portes de sous-sol / technique coupe-feu EI30", "pcs", 12, 2400.00, {"bkp": "221", "din276": "330"}),
            ],
        ),
        # ── BKP 222 Facade, crepi ─────────────────────────────────
        (
            "222",
            "CFC 222 - Facade, crepi",
            {"bkp": "222", "din276": "330"},
            [
                ("222.1", "Isolation peripherique EPS 200mm (Minergie)", "m2", 5200, 68.00, {"bkp": "222", "din276": "330"}),
                ("222.2", "Crepi exterieur enduit mineral 2 couches", "m2", 5200, 52.00, {"bkp": "222", "din276": "330"}),
                ("222.3", "Soubassement etancheite + revetement", "m2", 480, 88.00, {"bkp": "222", "din276": "330"}),
                ("222.4", "Balcons beton arme + isolation thermique", "m2", 1440, 285.00, {"bkp": "222", "din276": "330"}),
                ("222.5", "Garde-corps balcons acier galvanise", "m", 960, 245.00, {"bkp": "222", "din276": "330"}),
            ],
        ),
        # ── BKP 224 Toiture ───────────────────────────────────────
        (
            "224",
            "CFC 224 - Toiture",
            {"bkp": "224", "din276": "330"},
            [
                ("224.1", "Isolation thermique PIR 200-280mm", "m2", 2100, 88.00, {"bkp": "224", "din276": "330"}),
                ("224.2", "Etancheite toiture FPO 2 couches", "m2", 2100, 65.00, {"bkp": "224", "din276": "330"}),
                ("224.3", "Vegetalisation extensive", "m2", 1400, 72.00, {"bkp": "224", "din276": "330"}),
                ("224.4", "Acrotere habillage aluminium", "m", 480, 78.00, {"bkp": "224", "din276": "330"}),
                ("224.5", "Coupole / exutoire de fumee cages escalier", "pcs", 3, 5600.00, {"bkp": "224", "din276": "330"}),
                ("224.6", "Installation PV toiture 120 kWp", "lsum", 1, 248000.00, {"bkp": "224", "din276": "330"}),
            ],
        ),
        # ── BKP 225 Amenagement interieur 1 (cloisons, portes) ────
        (
            "225",
            "CFC 225 - Amenagement interieur 1, cloisons et portes",
            {"bkp": "225", "din276": "330"},
            [
                ("225.1", "Cloisons placo BA13 double parement", "m2", 8400, 68.00, {"bkp": "225", "din276": "330"}),
                ("225.2", "Cloisons coupe-feu EI60", "m2", 1200, 145.00, {"bkp": "225", "din276": "330"}),
                ("225.3", "Portes interieures bois ame pleine", "pcs", 360, 780.00, {"bkp": "225", "din276": "330"}),
                ("225.4", "Portes coupe-feu EI30", "pcs", 48, 1650.00, {"bkp": "225", "din276": "330"}),
                ("225.5", "Portes palier blindees", "pcs", 72, 1950.00, {"bkp": "225", "din276": "330"}),
            ],
        ),
        # ── BKP 226 Amenagement interieur 2 (sols, plafonds) ──────
        (
            "226",
            "CFC 226 - Amenagement interieur 2, sols, plafonds, revetements",
            {"bkp": "226", "din276": "330"},
            [
                ("226.1", "Chape ciment CT-C25-F4 flottante", "m2", 10200, 35.00, {"bkp": "226", "din276": "330"}),
                ("226.2", "Isolation acoustique MW-T 30mm", "m2", 10200, 17.50, {"bkp": "226", "din276": "330"}),
                ("226.3", "Parquet chene contrecolle sejour/chambres", "m2", 5400, 82.00, {"bkp": "226", "din276": "330"}),
                ("226.4", "Carrelage gres cerame salles de bain", "m2", 2400, 78.00, {"bkp": "226", "din276": "330"}),
                ("226.5", "Carrelage gres cerame cuisines / entrees", "m2", 1800, 72.00, {"bkp": "226", "din276": "330"}),
                ("226.6", "Faux-plafond placo acoustique", "m2", 3600, 58.00, {"bkp": "226", "din276": "330"}),
                ("226.7", "Peinture interieure dispersion 2 couches", "m2", 28000, 11.50, {"bkp": "226", "din276": "330"}),
                ("226.8", "Faience murale salles de bain", "m2", 2400, 75.00, {"bkp": "226", "din276": "330"}),
                ("226.9", "Plinthes MDF peint", "m", 7200, 14.50, {"bkp": "226", "din276": "330"}),
            ],
        ),
        # ── BKP 230 Installations electriques ─────────────────────
        (
            "230",
            "CFC 230 - Installations electriques",
            {"bkp": "230", "din276": "440"},
            [
                ("230.1", "Raccordement reseau + coffret general", "lsum", 1, 78000.00, {"bkp": "230", "din276": "440"}),
                ("230.2", "Tableaux electriques par immeuble", "pcs", 3, 18500.00, {"bkp": "230", "din276": "440"}),
                ("230.3", "Tableau divisionnaire par appartement", "pcs", 72, 2800.00, {"bkp": "230", "din276": "440"}),
                ("230.4", "Canalisations + cablage appartements", "m2", 10200, 42.00, {"bkp": "230", "din276": "440"}),
                ("230.5", "Eclairage LED parties communes", "m2", 2400, 52.00, {"bkp": "230", "din276": "440"}),
                ("230.6", "Eclairage de securite central", "lsum", 1, 68000.00, {"bkp": "230", "din276": "440"}),
                ("230.7", "Parafoudre + mise a terre", "lsum", 1, 48000.00, {"bkp": "230", "din276": "440"}),
            ],
        ),
        # ── BKP 240 Chauffage ─────────────────────────────────────
        (
            "240",
            "CFC 240 - Chauffage",
            {"bkp": "240", "din276": "420"},
            [
                ("240.1", "Pompe a chaleur sol/eau sonde geothermique 280 kW", "lsum", 1, 285000.00, {"bkp": "240", "din276": "420"}),
                ("240.2", "Sondes geothermiques 12 x 200m", "m", 2400, 68.00, {"bkp": "240", "din276": "420"}),
                ("240.3", "Accumulateur tampon 3000 L", "pcs", 2, 9500.00, {"bkp": "240", "din276": "420"}),
                ("240.4", "Distribution chauffage colonnes montantes", "m", 2400, 45.00, {"bkp": "240", "din276": "420"}),
                ("240.5", "Chauffage au sol PE-Xa 20mm", "m2", 8400, 48.00, {"bkp": "240", "din276": "420"}),
                ("240.6", "Radiateurs seche-serviettes salles de bain", "pcs", 108, 420.00, {"bkp": "240", "din276": "420"}),
            ],
        ),
        # ── BKP 241 Ventilation ───────────────────────────────────
        (
            "241",
            "CFC 241 - Ventilation",
            {"bkp": "241", "din276": "420"},
            [
                ("241.1", "VMC double-flux avec recuperation par appartement", "pcs", 72, 4800.00, {"bkp": "241", "din276": "420"}),
                ("241.2", "Gaines de ventilation galvanisees", "m", 3600, 52.00, {"bkp": "241", "din276": "420"}),
                ("241.3", "Clapets coupe-feu EI90", "pcs", 96, 320.00, {"bkp": "241", "din276": "420"}),
                ("241.4", "Ventilation parking souterrain CO", "lsum", 1, 85000.00, {"bkp": "241", "din276": "420"}),
            ],
        ),
        # ── BKP 242 Sanitaire ─────────────────────────────────────
        (
            "242",
            "CFC 242 - Installations sanitaires",
            {"bkp": "242", "din276": "420"},
            [
                ("242.1", "Canalisations de base SML/PE DN100-DN200", "m", 960, 68.00, {"bkp": "242", "din276": "420"}),
                ("242.2", "Colonnes eaux usees / pluviales", "m", 1440, 52.00, {"bkp": "242", "din276": "420"}),
                ("242.3", "Distribution eau froide/chaude PE-Xc", "m", 5400, 48.00, {"bkp": "242", "din276": "420"}),
                ("242.4", "Appareils sanitaires WC/lavabo/baignoire", "pcs", 288, 1380.00, {"bkp": "242", "din276": "420"}),
                ("242.5", "Robinetterie mitigeurs", "pcs", 216, 285.00, {"bkp": "242", "din276": "420"}),
                ("242.6", "Cuisines installations eau/evacuation", "pcs", 72, 680.00, {"bkp": "242", "din276": "420"}),
                ("242.7", "Isolation tuyauteries MuKEn", "m", 5400, 16.50, {"bkp": "242", "din276": "420"}),
            ],
        ),
        # ── BKP 250 Ascenseurs ────────────────────────────────────
        (
            "250",
            "CFC 250 - Ascenseurs",
            {"bkp": "250", "din276": "410"},
            [
                ("250.1", "Ascenseur 630 kg / 8 personnes, 7 arrets", "pcs", 3, 145000.00, {"bkp": "250", "din276": "410"}),
            ],
        ),
        # ── BKP 280 Frais annexes ─────────────────────────────────
        (
            "280",
            "CFC 280 - Frais annexes, honoraires",
            {"bkp": "280", "din276": "350"},
            [
                ("280.1", "Honoraires architecte SIA 102", "lsum", 1, 1850000.00, {"bkp": "280", "din276": "350"}),
                ("280.2", "Honoraires ingenieur civil SIA 108", "lsum", 1, 680000.00, {"bkp": "280", "din276": "350"}),
                ("280.3", "Honoraires CVSE SIA 108", "lsum", 1, 520000.00, {"bkp": "280", "din276": "350"}),
                ("280.4", "Direction des travaux", "lsum", 1, 480000.00, {"bkp": "280", "din276": "350"}),
            ],
        ),
        # ── BKP 420 Amenagements exterieurs ───────────────────────
        (
            "420",
            "CFC 420 - Amenagements exterieurs",
            {"bkp": "420", "din276": "500"},
            [
                ("420.1", "Terrassement amenagements exterieurs", "m3", 1200, 28.00, {"bkp": "420", "din276": "500"}),
                ("420.2", "Rampe parking souterrain beton + chauffage", "m2", 140, 295.00, {"bkp": "420", "din276": "500"}),
                ("420.3", "Surfaces circulation enrobes + paves", "m2", 1400, 88.00, {"bkp": "420", "din276": "500"}),
                ("420.4", "Plantations arbres + massifs", "pcs", 24, 2200.00, {"bkp": "420", "din276": "500"}),
                ("420.5", "Eclairage exterieur mats + bornes", "pcs", 22, 1650.00, {"bkp": "420", "din276": "500"}),
                ("420.6", "Places a velo couvertes", "pcs", 96, 380.00, {"bkp": "420", "din276": "500"}),
                ("420.7", "Aire de jeux enfants", "lsum", 1, 42000.00, {"bkp": "420", "din276": "500"}),
            ],
        ),
    ],
    markups=[
        ("Frais generaux de chantier (BGK)", 9.0, "overhead", "direct_cost"),
        ("Frais generaux d'entreprise (AGK)", 7.0, "overhead", "direct_cost"),
        ("Risque (R)", 2.5, "contingency", "direct_cost"),
        ("Benefice (G)", 4.5, "profit", "direct_cost"),
        ("TVA (MWST)", 8.1, "tax", "cumulative"),
    ],
    total_months=24,
    tender_name="Gros oeuvre",
    tender_companies=[
        ("Construct Romande SA, Lausanne", "soumission@construct-romande.example", 0.98),
        ("Batigroupe Leemann SA", "offre@batigroupe.example", 1.04),
        ("Entreprise Riondaz SA, Vevey", "soumission@riondaz.example", 1.01),
    ],
    project_metadata={
        "address": "Avenue du Flon 24, 1003 Lausanne",
        "client": "Regie Thalmann SA, Lausanne",
        "main_contractor": "Construct Romande SA, Lausanne",
        "architect": "Atelier Vaudaire Architectes SIA, Lausanne",
        "structural_engineer": "Ingenierie Structurale Genoud SA",
        "mep_engineer": "Techniques du Batiment Morand SA",
        "gfa_m2": 12600,
        "residential_units": 72,
        "gv_m3": 42000,
        "storeys_above": 6,
        "storeys_below": 1,
        "parking_spaces": 48,
        "structure_system": "Dalle plate beton arme / RC flat slab on walls and columns, raft foundation",
        "facade_system": "Crepi sur isolation peripherique EPS 200mm, menuiseries bois-metal triple vitrage",
        "energy_standard": "Minergie",
        "design_phase": "SIA 112 Phase 32 Projet de construction / Devis",
        "applicable_standards": [
            "SIA 451 (Planification des couts de construction)",
            "CFC/BKP (CRB)",
            "SIA 118:2013 (Conditions generales pour travaux de construction)",
            "SIA 180 (Protection thermique et protection contre l'humidite)",
            "SIA 181 (Protection contre le bruit)",
            "Minergie Standard",
        ],
        "permit_authority": "Service d'urbanisme de la Ville de Lausanne (LATC)",
        "cost_basis": "CRB-benchmarks 2025/26, facteur regional Lausanne/Vaud",
    },
    tender_packages=[
        (
            "Gros oeuvre",
            "Fouille, fondation, structure beton arme, voiles, dalles",
            "evaluating",
            [
                ("Construct Romande SA, Lausanne", "soumission@construct-romande.example", 0.98),
                ("Batigroupe Leemann SA", "offre@batigroupe.example", 1.04),
                ("Entreprise Riondaz SA, Vevey", "soumission@riondaz.example", 1.01),
            ],
        ),
        (
            "Enveloppe / Facade",
            "Isolation, crepi, fenetres, stores, etancheite toiture",
            "evaluating",
            [
                ("Facades Romand SA", "soumission@facades-romand.example", 0.97),
                ("Menuiserie Tschanz SA", "offre@tschanz.example", 1.03),
            ],
        ),
        (
            "CVSE (Chauffage/Ventilation/Sanitaire/Electricite)",
            "Geothermie, chauffage sol, VMC, sanitaire, raccordements",
            "evaluating",
            [
                ("Techniques du Batiment Morand SA", "soumission@morand-tb.example", 0.99),
                ("Energies Vertes Vaudoises SA", "offre@energies-vv.example", 1.05),
            ],
        ),
        (
            "Amenagement interieur",
            "Cloisons, portes, chapes, revetements sols, peinture",
            "draft",
            [
                ("Interieurs Gruyere SA", "soumission@interieurs-gruyere.example", 0.97),
                ("Batipeinture Leman SA", "offre@batipeinture.example", 1.02),
            ],
        ),
    ],
)
