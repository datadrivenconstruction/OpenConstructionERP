# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Flagship demo: Commercial office building, Montréal (Québec, Canada)
# Pack: batimatech-ca - CAD / fr-CA / MasterFormat 2020
#
# Program: Class-A speculative office, 8 above-grade storeys + 2 basement
# levels (parking + mechanical). GFA ~12 400 m² above grade, ~3 800 m²
# basement. Cast-in-place reinforced concrete superstructure (CSA A23.3),
# composite steel floor framing on the office floors (CSA S16), curtain-wall
# envelope. NBC 2020 + Code de construction du Québec (CCQ). Designed to
# LEED v4 Gold / Novoclimat commercial intent. Seismic: NBC 2020 Site
# Class C, Montréal high-seismicity zone. Construction cost ~46 M CAD
# direct (Montréal Q1-2026 price level, before taxes), ~58 M CAD with
# General Conditions / Overhead & Profit / contingency.
# Stipulated-price contract CCDC 2 (2020).
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-montreal",
    project_name="Édifice de bureaux Montréal - Griffintown",
    project_description=(
        "Immeuble de bureaux commercial de catégorie A, 8 étages hors sol + "
        "2 niveaux de sous-sol (stationnement et locaux techniques). "
        "Superficie brute hors sol env. 12 400 m², sous-sol env. 3 800 m². "
        "Structure en béton armé coulé en place (CSA A23.3) avec planchers "
        "mixtes acier-béton aux étages de bureaux (CSA S16). "
        "Enveloppe en mur-rideau verre-aluminium. "
        "Conforme au CNB 2020 et au Code de construction du Québec (CCQ). "
        "Cible LEED v4 Or / Novoclimat commercial. "
        "Zone sismique élevée (Montréal, catégorie de sol C). "
        "Contrat à forfait CCDC 2 (2020). "
        "Coût de construction env. 46 M CAD en coûts directs (~58 M CAD "
        "avec conditions générales, frais généraux, profit et imprévus; "
        "niveau de prix Montréal 2026, hors taxes)."
    ),
    region="CA",
    subdivision_code="CA-QC",
    classification_standard="masterformat",
    currency="CAD",
    locale="fr-CA",
    address={
        "street": "1200 rue Ottawa",
        "city": "Montréal",
        "postcode": "H3C 1S2",
        "country": "Canada",
        "lat": 45.4948,
        "lng": -73.5610,
    },
    validation_rule_sets=["masterformat", "boq_quality"],
    boq_name="Estimation détaillée - par divisions normalisées",
    boq_description=(
        "Estimation détaillée de classe B (devis préliminaire) selon "
        "Divisions normalisées 03 à 32. Coûts directs en CAD."
    ),
    boq_metadata={
        "standard": "Classification par divisions normalisées",
        "phase": "Estimation classe B / Documents préliminaires (DD)",
        "base_date": "2026-Q1",
        "price_level": "Montréal 2026",
    },
    sections=[
        # ── Division 31 - Travaux de terrassement (Excavation, grading and earth support) ──────────
        (
            "31",
            "Division 31 - Terrassement (Excavation, grading and earth support)",
            {"masterformat": "31 00 00"},
            [
                ("31.1", "Démolition et préparation du site (Site clearing)", "lsum", 1, 95000.00, {"masterformat": "31 10 00"}),
                ("31.2", "Excavation de masse, sol (Mass excavation)", "m3", 18500, 22.50, {"masterformat": "31 23 16"}),
                ("31.3", "Excavation de roc dynamitage (Rock blasting excavation)", "m3", 2200, 145.00, {"masterformat": "31 23 16"}),
                ("31.4", "Étançonnement pieux sécants (Secant pile shoring)", "m2", 3400, 285.00, {"masterformat": "31 50 00"}),
                ("31.5", "Ancrages précontraints terrain (Tieback anchors)", "pcs", 48, 4800.00, {"masterformat": "31 51 00"}),
                ("31.6", "Contrôle des eaux souterraines (Dewatering)", "lsum", 1, 165000.00, {"masterformat": "31 23 19"}),
                ("31.7", "Remblai compacté granulaire (Compacted granular fill)", "m3", 4200, 38.00, {"masterformat": "31 23 23"}),
                ("31.8", "Transport et disposition des sols (Soil haul/disposal)", "m3", 16000, 28.50, {"masterformat": "31 23 23"}),
                ("31.9", "Gestion sols contaminés C-D (Contaminated soil mgmt)", "t", 1800, 95.00, {"masterformat": "31 25 00"}),
                ("31.10", "Étude géotechnique et instrumentation (Geotech survey)", "lsum", 1, 42000.00, {"masterformat": "31 09 00"}),
            ],
        ),
        # ── Division 03 - Béton (Cast-in-place and precast concrete work) ─────────────────────────────
        (
            "03",
            "Division 03 - Béton (Cast-in-place and precast concrete work)",
            {"masterformat": "03 00 00"},
            [
                ("03.1", "Béton de propreté 15 MPa (Blinding concrete)", "m3", 320, 215.00, {"masterformat": "03 30 00"}),
                ("03.2", "Radier 35 MPa, ép. 600 mm (Mat foundation slab)", "m3", 2280, 295.00, {"masterformat": "03 30 00"}),
                ("03.3", "Semelles et fondations 30 MPa (Footings/foundations)", "m3", 640, 285.00, {"masterformat": "03 30 00"}),
                ("03.4", "Murs de sous-sol 35 MPa étanches (Basement walls WT)", "m3", 1150, 340.00, {"masterformat": "03 30 00"}),
                ("03.5", "Colonnes béton 40 MPa (Concrete columns)", "m3", 580, 425.00, {"masterformat": "03 30 00"}),
                ("03.6", "Dalles sur tablier composite 30 MPa (Composite floor slabs)", "m3", 1860, 295.00, {"masterformat": "03 30 00"}),
                ("03.7", "Noyau de cisaillement / ascenseur 40 MPa (Shear core)", "m3", 920, 410.00, {"masterformat": "03 30 00"}),
                ("03.8", "Coffrage murs et noyau (Wall/core formwork)", "m2", 11800, 68.00, {"masterformat": "03 11 00"}),
                ("03.9", "Coffrage dalles et tables volantes (Slab formwork)", "m2", 14200, 52.00, {"masterformat": "03 11 00"}),
                ("03.10", "Coffrage colonnes (Column formwork)", "m2", 3200, 75.00, {"masterformat": "03 11 00"}),
                ("03.11", "Armature 400W posée (Reinforcing steel placed)", "t", 1240, 2350.00, {"masterformat": "03 21 00"}),
                ("03.12", "Treillis métallique soudé (Welded wire mesh)", "m2", 16400, 8.50, {"masterformat": "03 22 00"}),
                ("03.13", "Finition durcie au quartz, stationnement (Hardened floor finish)", "m2", 7200, 14.50, {"masterformat": "03 35 00"}),
                ("03.14", "Cure et scellant béton (Concrete cure/seal)", "m2", 18000, 4.20, {"masterformat": "03 39 00"}),
            ],
        ),
        # ── Division 04 - Maçonnerie (Brick, block and stone work) ─────────────────────────
        (
            "04",
            "Division 04 - Maçonnerie (Brick, block and stone work)",
            {"masterformat": "04 00 00"},
            [
                ("04.1", "Blocs de béton 200 mm cages d'escalier (CMU stair walls)", "m2", 3400, 165.00, {"masterformat": "04 22 00"}),
                ("04.2", "Blocs de béton 150 mm cloisons techniques (CMU service walls)", "m2", 1800, 145.00, {"masterformat": "04 22 00"}),
                ("04.3", "Parement de brique d'argile (Clay brick veneer)", "m2", 1250, 285.00, {"masterformat": "04 21 13"}),
                ("04.4", "Pierre calcaire de Saint-Marc, socle (Limestone base course)", "m2", 420, 595.00, {"masterformat": "04 43 00"}),
                ("04.5", "Armature de joint et attaches (Joint reinf/ties)", "m2", 5200, 9.50, {"masterformat": "04 05 23"}),
                ("04.6", "Linteaux et appuis préfabriqués (Precast lintels/sills)", "m", 380, 95.00, {"masterformat": "04 05 00"}),
            ],
        ),
        # ── Division 05 - Métaux (Structural and miscellaneous metal work) ──────────────────────────────
        (
            "05",
            "Division 05 - Métaux (Structural and miscellaneous metal work)",
            {"masterformat": "05 00 00"},
            [
                ("05.1", "Charpente d'acier poutres/poutrelles (Structural steel framing)", "t", 580, 5200.00, {"masterformat": "05 12 00"}),
                ("05.2", "Tablier métallique composite (Composite steel deck)", "m2", 9600, 42.00, {"masterformat": "05 31 00"}),
                ("05.3", "Goujons de cisaillement Nelson (Shear stud connectors)", "pcs", 24000, 3.80, {"masterformat": "05 12 00"}),
                ("05.4", "Tablier de toiture métallique (Steel roof deck)", "m2", 1600, 38.00, {"masterformat": "05 31 00"}),
                ("05.5", "Escaliers d'acier et paliers (Steel stairs/landings)", "pcs", 18, 8500.00, {"masterformat": "05 51 00"}),
                ("05.6", "Garde-corps et mains courantes acier (Steel railings)", "m", 620, 245.00, {"masterformat": "05 52 00"}),
                ("05.7", "Acier divers et supports (Miscellaneous metals)", "t", 42, 6800.00, {"masterformat": "05 50 00"}),
                ("05.8", "Caillebotis et trappes d'accès (Grating/access hatches)", "m2", 180, 320.00, {"masterformat": "05 53 00"}),
                ("05.9", "Protection anti-feu projetée charpente (Spray fireproofing)", "m2", 11200, 18.50, {"masterformat": "05 12 00"}),
            ],
        ),
        # ── Division 07 - Isolation et étanchéité (Roofing, waterproofing and insulation) ───
        (
            "07",
            "Division 07 - Isolation et étanchéité (Roofing, waterproofing and insulation)",
            {"masterformat": "07 00 00"},
            [
                ("07.1", "Imperméabilisation bentonite sous-sol (Bentonite waterproofing)", "m2", 5600, 58.00, {"masterformat": "07 13 00"}),
                ("07.2", "Membrane d'air et d'humidité (Air/vapour barrier)", "m2", 13800, 24.00, {"masterformat": "07 27 00"}),
                ("07.3", "Isolant rigide ext. continu R-25 (Continuous rigid insul.)", "m2", 13800, 38.00, {"masterformat": "07 21 00"}),
                ("07.4", "Membrane de toiture TPO 60 mil (TPO roof membrane)", "m2", 1750, 78.00, {"masterformat": "07 54 00"}),
                ("07.5", "Isolant de toiture polyiso R-35 (Roof insulation)", "m2", 1750, 56.00, {"masterformat": "07 22 00"}),
                ("07.6", "Toiture verte extensive (Extensive green roof)", "m2", 480, 165.00, {"masterformat": "07 55 63"}),
                ("07.7", "Solins et ferblanterie (Flashing/sheet metal)", "m", 920, 62.00, {"masterformat": "07 62 00"}),
                ("07.8", "Calfeutrage et scellants (Joint sealants)", "m", 4800, 14.50, {"masterformat": "07 92 00"}),
                ("07.9", "Coupe-feu pénétrations (Firestopping penetrations)", "lsum", 1, 145000.00, {"masterformat": "07 84 00"}),
                ("07.10", "Pare-feu et coupe-fumée registres (Firewall/smoke seals)", "m", 680, 95.00, {"masterformat": "07 84 00"}),
            ],
        ),
        # ── Division 08 - Ouvertures (Doors, windows and glazed assemblies) ────────────────────────
        (
            "08",
            "Division 08 - Ouvertures (Doors, windows and glazed assemblies)",
            {"masterformat": "08 00 00"},
            [
                ("08.1", "Mur-rideau verre-alu unitisé (Unitized curtain wall)", "m2", 8900, 685.00, {"masterformat": "08 44 00"}),
                ("08.2", "Vitrage isolant triple performance (Triple-glazed IGU)", "m2", 1200, 380.00, {"masterformat": "08 80 00"}),
                ("08.3", "Portes d'entrée vitrées automatiques (Automatic entrances)", "pcs", 4, 18500.00, {"masterformat": "08 42 29"}),
                ("08.4", "Portes d'acier creuses cadres (Hollow metal doors/frames)", "pcs", 165, 1250.00, {"masterformat": "08 11 13"}),
                ("08.5", "Portes de bois âme massive (Solid-core wood doors)", "pcs", 240, 850.00, {"masterformat": "08 14 16"}),
                ("08.6", "Portes coupe-feu 90 min (90-min fire doors)", "pcs", 86, 1850.00, {"masterformat": "08 11 13"}),
                ("08.7", "Quincaillerie de porte (Finish hardware)", "pcs", 491, 620.00, {"masterformat": "08 71 00"}),
                ("08.8", "Cloisons vitrées de bureau (Interior glazed partitions)", "m2", 2400, 320.00, {"masterformat": "08 80 00"}),
                ("08.9", "Lanterneaux et puits de lumière (Skylights)", "m2", 120, 1450.00, {"masterformat": "08 62 00"}),
                ("08.10", "Portes sectionnelles quai (Overhead loading doors)", "pcs", 3, 9500.00, {"masterformat": "08 36 00"}),
            ],
        ),
        # ── Division 09 - Finitions (Interior finishing) ─────────────────────────
        (
            "09",
            "Division 09 - Finitions (Interior finishing)",
            {"masterformat": "09 00 00"},
            [
                ("09.1", "Ossature métallique cloisons (Metal stud framing)", "m2", 18600, 38.00, {"masterformat": "09 22 16"}),
                ("09.2", "Gypse type X 2 faces (Gypsum board both sides)", "m2", 37200, 28.00, {"masterformat": "09 29 00"}),
                ("09.3", "Cloison acoustique STC 50 (Acoustic partition)", "m2", 3200, 72.00, {"masterformat": "09 21 00"}),
                ("09.4", "Plafond suspendu en T (Acoustic tile ceiling)", "m2", 9800, 48.00, {"masterformat": "09 51 00"}),
                ("09.5", "Plafond gypse suspendu (Suspended gypsum ceiling)", "m2", 2800, 62.00, {"masterformat": "09 29 00"}),
                ("09.6", "Carrelage céramique murs sanitaires (Ceramic wall tile)", "m2", 1850, 88.00, {"masterformat": "09 30 00"}),
                ("09.7", "Carrelage porcelaine planchers (Porcelain floor tile)", "m2", 2200, 110.00, {"masterformat": "09 30 00"}),
                ("09.8", "Tapis modulaire bureaux (Carpet tile)", "m2", 8400, 52.00, {"masterformat": "09 68 00"}),
                ("09.9", "Plancher vinyle de luxe LVT (Luxury vinyl tile)", "m2", 2600, 68.00, {"masterformat": "09 65 00"}),
                ("09.10", "Plancher époxydique stationnement (Epoxy parking floor)", "m2", 1200, 42.00, {"masterformat": "09 67 00"}),
                ("09.11", "Peinture intérieure 2 couches (Interior paint)", "m2", 42000, 11.50, {"masterformat": "09 91 00"}),
                ("09.12", "Plinthes et moulures (Base and trim)", "m", 6800, 12.00, {"masterformat": "09 64 00"}),
                ("09.13", "Panneaux acoustiques muraux (Acoustic wall panels)", "m2", 680, 145.00, {"masterformat": "09 84 00"}),
            ],
        ),
        # ── Division 14 - Appareils de levage (Elevators, escalators and lifts) ──────────────
        (
            "14",
            "Division 14 - Appareils de levage (Elevators, escalators and lifts)",
            {"masterformat": "14 00 00"},
            [
                ("14.1", "Ascenseur passagers 1600 kg, 10 arrêts (Passenger elevator)", "pcs", 4, 285000.00, {"masterformat": "14 21 00"}),
                ("14.2", "Ascenseur monte-charge 2500 kg (Freight elevator)", "pcs", 1, 345000.00, {"masterformat": "14 21 00"}),
                ("14.3", "Portes palières acier inox (Stainless landing doors)", "pcs", 55, 4200.00, {"masterformat": "14 28 00"}),
                ("14.4", "Système de gestion d'ascenseurs (Elevator dispatch system)", "lsum", 1, 65000.00, {"masterformat": "14 28 00"}),
            ],
        ),
        # ── Division 21 - Protection incendie (Sprinkler and fire-suppression systems) ───────
        (
            "21",
            "Division 21 - Protection incendie (Sprinkler and fire-suppression systems)",
            {"masterformat": "21 00 00"},
            [
                ("21.1", "Réseau de gicleurs automatiques (Automatic sprinkler system)", "m2", 16200, 24.50, {"masterformat": "21 13 00"}),
                ("21.2", "Pompe incendie diesel + jockey (Fire pump diesel/jockey)", "pcs", 1, 145000.00, {"masterformat": "21 30 00"}),
                ("21.3", "Colonnes montantes et raccords pompiers (Standpipes)", "m", 240, 285.00, {"masterformat": "21 12 00"}),
                ("21.4", "Cabinets et extincteurs portatifs (Hose cabinets/extinguishers)", "pcs", 95, 480.00, {"masterformat": "21 10 00"}),
                ("21.5", "Système gaz inerte salle serveurs (Clean-agent suppression)", "lsum", 1, 95000.00, {"masterformat": "21 22 00"}),
            ],
        ),
        # ── Division 22 - Plomberie (Piping systems and sanitary fixtures) ─────────────────────────
        (
            "22",
            "Division 22 - Plomberie (Piping systems and sanitary fixtures)",
            {"masterformat": "22 00 00"},
            [
                ("22.1", "Réseau d'évacuation et ventilation fonte/PVC (Sanitary/vent)", "m", 2400, 78.00, {"masterformat": "22 13 00"}),
                ("22.2", "Réseau d'alimentation eau cuivre/PEX (Domestic water piping)", "m", 3200, 62.00, {"masterformat": "22 11 00"}),
                ("22.3", "Drainage pluvial intérieur (Storm drainage interior)", "m", 1100, 92.00, {"masterformat": "22 14 00"}),
                ("22.4", "Appareils sanitaires complets (Plumbing fixtures complete)", "pcs", 180, 1450.00, {"masterformat": "22 40 00"}),
                ("22.5", "Chauffe-eau électrique 400 L (Electric water heater)", "pcs", 6, 6800.00, {"masterformat": "22 33 00"}),
                ("22.6", "Pompes de puisard duplex (Duplex sump pumps)", "pcs", 4, 5200.00, {"masterformat": "22 14 29"}),
                ("22.7", "Récupération eaux grises citerne (Greywater harvesting)", "lsum", 1, 85000.00, {"masterformat": "22 13 00"}),
                ("22.8", "Isolation tuyauterie (Pipe insulation)", "m", 5600, 18.00, {"masterformat": "22 07 00"}),
            ],
        ),
        # ── Division 23 - CVCA (Heating, cooling and ventilation systems) ──────────────────────────────────
        (
            "23",
            "Division 23 - Chauffage, ventilation, climatisation (Heating, cooling and ventilation systems)",
            {"masterformat": "23 00 00"},
            [
                ("23.1", "Unités de traitement d'air avec récup. (AHU with heat recovery)", "pcs", 6, 145000.00, {"masterformat": "23 73 00"}),
                ("23.2", "Refroidisseur centrifuge 600 t (Centrifugal chiller)", "pcs", 2, 285000.00, {"masterformat": "23 64 00"}),
                ("23.3", "Tour de refroidissement (Cooling tower)", "pcs", 2, 95000.00, {"masterformat": "23 65 00"}),
                ("23.4", "Chaudières à condensation gaz 1500 kW (Condensing boilers)", "pcs", 2, 78000.00, {"masterformat": "23 52 00"}),
                ("23.5", "Géothermie puits verticaux 150 m (Geothermal boreholes)", "pcs", 40, 18500.00, {"masterformat": "23 21 13"}),
                ("23.6", "Réseau de gaines tôle galvanisée (Galvanized ductwork)", "kg", 96000, 12.50, {"masterformat": "23 31 00"}),
                ("23.7", "Tuyauterie hydronique acier (Hydronic piping)", "m", 4200, 95.00, {"masterformat": "23 21 00"}),
                ("23.8", "Poutres froides actives (Active chilled beams)", "pcs", 620, 1850.00, {"masterformat": "23 82 00"}),
                ("23.9", "Diffuseurs et grilles (Diffusers/grilles)", "pcs", 1450, 145.00, {"masterformat": "23 37 00"}),
                ("23.10", "Registres coupe-feu et coupe-fumée (Fire/smoke dampers)", "pcs", 320, 420.00, {"masterformat": "23 33 00"}),
                ("23.11", "Régulation automatique du bâtiment (BAS/DDC controls)", "lsum", 1, 485000.00, {"masterformat": "23 09 00"}),
                ("23.12", "Équilibrage et mise en service (TAB/commissioning)", "lsum", 1, 125000.00, {"masterformat": "23 05 93"}),
                ("23.13", "Ventilation stationnement CO (Garage CO ventilation)", "pcs", 8, 14500.00, {"masterformat": "23 34 00"}),
            ],
        ),
        # ── Division 26 - Électricité (Power distribution and lighting systems) ─────────────────────
        (
            "26",
            "Division 26 - Électricité (Power distribution and lighting systems)",
            {"masterformat": "26 00 00"},
            [
                ("26.1", "Entrée électrique 2000 A, 600 V (Main service 2000A)", "lsum", 1, 285000.00, {"masterformat": "26 24 00"}),
                ("26.2", "Transformateurs secs 1500 kVA (Dry-type transformers)", "pcs", 3, 42000.00, {"masterformat": "26 22 00"}),
                ("26.3", "Génératrice diesel 800 kW + ATS (Diesel generator/ATS)", "pcs", 1, 385000.00, {"masterformat": "26 32 13"}),
                ("26.4", "Panneaux de distribution par étage (Distribution panels)", "pcs", 32, 8500.00, {"masterformat": "26 24 16"}),
                ("26.5", "Chemins de câbles et conduits (Cable tray/conduit)", "m", 9600, 38.00, {"masterformat": "26 05 00"}),
                ("26.6", "Câblage de force et dérivations (Power wiring/branch)", "m", 62000, 6.20, {"masterformat": "26 05 19"}),
                ("26.7", "Luminaires DEL bureaux (LED office luminaires)", "pcs", 2800, 285.00, {"masterformat": "26 51 00"}),
                ("26.8", "Éclairage de secours et issues (Emergency/exit lighting)", "pcs", 380, 245.00, {"masterformat": "26 52 00"}),
                ("26.9", "Commandes d'éclairage DALI (DALI lighting controls)", "lsum", 1, 165000.00, {"masterformat": "26 09 23"}),
                ("26.10", "Mise à la terre et liaison (Grounding/bonding)", "lsum", 1, 65000.00, {"masterformat": "26 05 26"}),
                ("26.11", "Bornes de recharge VÉ niveau 2 (EV charging stations L2)", "pcs", 40, 6500.00, {"masterformat": "26 27 00"}),
                ("26.12", "Parafoudre et conditionnement (Surge protection)", "pcs", 32, 1850.00, {"masterformat": "26 43 00"}),
            ],
        ),
        # ── Division 27 - Réseaux de communication (Voice, data and network cabling) ───────────────────────
        (
            "27",
            "Division 27 - Réseaux de communication (Voice, data and network cabling)",
            {"masterformat": "27 00 00"},
            [
                ("27.1", "Câblage structuré cat. 6A (Structured cabling cat.6A)", "m", 48000, 4.80, {"masterformat": "27 15 00"}),
                ("27.2", "Salles de télécommunications équipées (Telecom rooms)", "pcs", 9, 28000.00, {"masterformat": "27 11 00"}),
                ("27.3", "Réseau de fibre optique vertical (Backbone fibre)", "m", 2400, 14.50, {"masterformat": "27 13 00"}),
                ("27.4", "Système d'amplification cellulaire DAS (Distributed antenna)", "lsum", 1, 145000.00, {"masterformat": "27 53 00"}),
                ("27.5", "Système audiovisuel salles de réunion (AV systems)", "pcs", 24, 12500.00, {"masterformat": "27 41 00"}),
                ("27.6", "Contrôle d'accès et caméras IP (Access control/CCTV)", "lsum", 1, 285000.00, {"masterformat": "28 20 00"}),
            ],
        ),
        # ── Division 32 - Aménagement extérieur (Paving, landscaping and site amenities) ─
        (
            "32",
            "Division 32 - Aménagement extérieur (Paving, landscaping and site amenities)",
            {"masterformat": "32 00 00"},
            [
                ("32.1", "Pavage asphalte accès et quai (Asphalt paving)", "m2", 1800, 58.00, {"masterformat": "32 12 00"}),
                ("32.2", "Pavés de béton place publique (Concrete pavers plaza)", "m2", 1400, 145.00, {"masterformat": "32 14 00"}),
                ("32.3", "Trottoirs et bordures béton (Concrete walks/curbs)", "m2", 980, 95.00, {"masterformat": "32 16 00"}),
                ("32.4", "Plantation arbres et arbustes (Trees/shrubs planting)", "pcs", 85, 850.00, {"masterformat": "32 93 00"}),
                ("32.5", "Gazon et engazonnement (Sod/seeding)", "m2", 1200, 22.00, {"masterformat": "32 92 00"}),
                ("32.6", "Mobilier urbain et supports vélos (Site furnishings/bike racks)", "lsum", 1, 95000.00, {"masterformat": "32 33 00"}),
                ("32.7", "Éclairage extérieur DEL (Exterior LED lighting)", "pcs", 38, 2400.00, {"masterformat": "26 56 00"}),
                ("32.8", "Bassin de rétention pluviale (Stormwater retention)", "lsum", 1, 165000.00, {"masterformat": "33 40 00"}),
                ("32.9", "Irrigation goutte-à-goutte (Drip irrigation)", "m2", 1200, 18.00, {"masterformat": "32 84 00"}),
            ],
        ),
    ],
    markups=[
        ("General Conditions (Conditions générales)", 9.0, "overhead", "direct_cost"),
        ("Overhead & Profit (Frais généraux et profit)", 8.0, "profit", "direct_cost"),
        ("Contingency (Imprévus de conception)", 7.0, "contingency", "direct_cost"),
    ],
    total_months=26,
    tender_name="Charpente et structure (Structure)",
    tender_companies=[
        ("Marcheval inc.", "soumissions@marcheval.example", 0.98),
        ("Tersac inc.", "estimation@tersac.example", 1.04),
        ("Vandrel Construction", "bids@vandrel.example", 1.02),
    ],
    project_metadata={
        "address": "1200 rue Ottawa, Montréal (Québec) H3C 1S2",
        "client": "Ravelance Développement Immobilier inc.",
        "architect": "Duhaime + Vasselin",
        "structural_engineer": "Norvenor Canada",
        "general_contractor_form": "CCDC 2 (2020) - contrat à forfait",
        "gfa_above_grade_m2": 12400,
        "gfa_basement_m2": 3800,
        "storeys": 8,
        "basement_levels": 2,
        "parking_spaces": 165,
        "structure_system": "Béton armé coulé en place + planchers mixtes acier-béton",
        "codes": [
            "Code national du bâtiment - Canada (CNB) 2020",
            "Code de construction du Québec (CCQ), chapitre I Bâtiment",
            "CSA A23.1/A23.3 - béton et calcul des structures en béton",
            "CSA S16 - règles de calcul des charpentes en acier",
            "CNB 2020 - exigences sismiques (Montréal, catégorie de sol C)",
        ],
        "permits": (
            "Permis de construction Ville de Montréal (arrondissement "
            "Le Sud-Ouest); approbation RBQ; PIIA Griffintown; "
            "autorisation MELCCFP gestion des sols excavés."
        ),
        "sustainability": "Cible LEED v4 BD+C: Core & Shell - niveau Or; Novoclimat commercial",
        "seismic": "CNB 2020, zone sismique élevée - Montréal, Site Class C, SFRS noyau en béton",
        "taxes_note": (
            "Taxes applicables en sus des coûts indiqués: TPS (GST) 5 % + "
            "TVQ (QST) 9,975 %, soit ~14,975 % cumulé. Les taxes ne sont "
            "PAS incluses dans les positions (coûts directs hors taxes)."
        ),
    },
    tender_packages=[
        (
            "Structure (Terrassement + Béton + Acier)",
            "Terrassement, étançonnement, béton coulé en place, charpente d'acier",
            "evaluating",
            [
                ("Marcheval inc.", "soumissions@marcheval.example", 0.98),
                ("Tersac inc.", "estimation@tersac.example", 1.04),
                ("Vandrel Construction", "bids@vandrel.example", 1.02),
            ],
        ),
        (
            "Enveloppe (Envelope)",
            "Mur-rideau, maçonnerie, isolation, étanchéité, toiture",
            "evaluating",
            [
                ("Marcheval Enveloppe", "enveloppe@marcheval.example", 0.97),
                ("Groupe Vitrerie Charbonneux", "soumissions@charbonneux.example", 1.05),
                ("Alcanor Architectural", "estimation@alcanor.example", 1.01),
            ],
        ),
        (
            "Mécanique CVCA + Plomberie (MEP Mechanical)",
            "Chauffage, ventilation, climatisation, géothermie, plomberie, gicleurs",
            "evaluating",
            [
                ("Thermovar / Plomberie Sancerel", "soumissions@sancerel.example", 0.99),
                ("Groupe Ardelin inc.", "estimation@ardelin.example", 1.06),
                ("Mécanique Delvray inc.", "bids@delvray.example", 1.03),
            ],
        ),
        (
            "Électricité + Communications (MEP Electrical)",
            "Distribution, génératrice, éclairage DEL, recharge VÉ, télécom, sécurité",
            "evaluating",
            [
                ("Chalonge & Associés Électrique", "soumissions@chalonge.example", 0.97),
                ("Vivelect inc.", "estimation@vivelect.example", 1.05),
                ("Marnault Électrique", "bids@marnault.example", 1.02),
            ],
        ),
        (
            "Finitions intérieures (Interior Finishes)",
            "Cloisons, gypse, plafonds, planchers, peinture, carrelage",
            "evaluating",
            [
                ("Constructions Velmy", "soumissions@velmy.example", 0.96),
                ("Ornevial Experts-Conseils", "estimation@ornevial.example", 1.04),
                ("Groupe Perrachon", "bids@perrachon.example", 1.01),
            ],
        ),
        (
            "Aménagement extérieur (External Works)",
            "Pavage, pavés, plantation, mobilier urbain, gestion pluviale",
            "evaluating",
            [
                ("Paysagiste Vernoy", "soumissions@vernoy.example", 0.99),
                ("Aménagement Clos Verdaine", "estimation@verdaine.example", 1.06),
            ],
        ),
    ],
)
