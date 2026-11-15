# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""German and French wording of the construction-control demo register's own prose.

The work package specs, laboratories, issuers and handover packages are written in English in ``seed.py``.
A German or French project reads them through this table, keyed by the exact English sentence, so a code, a
number or a name that is not listed passes through unchanged. English stays the default for every other language.
"""

from __future__ import annotations

from app.core.demo_locale_text import language_of

#: The kind of work a package covers, as the head of a sentence.
CATEGORY_TEXT: dict[str, dict[str, str]] = {
    "de": {
        "concrete": "Betonarbeiten",
        "drainage": "Entwässerungsarbeiten",
        "ductwork": "Lüftungskanalarbeiten",
        "electrical installation": "Elektroinstallationsarbeiten",
        "facade": "Fassadenarbeiten",
        "finishes": "Ausbauarbeiten",
        "foundations": "Gründungsarbeiten",
        "lifts": "Aufzugsarbeiten",
        "masonry": "Maurerarbeiten",
        "passive fire protection": "Arbeiten zum baulichen Brandschutz",
        "pavement": "Straßenbauarbeiten",
        "reinforcement": "Bewehrungsarbeiten",
        "roofing": "Dachabdichtungsarbeiten",
        "steelwork": "Stahlbauarbeiten",
        "waterproofing": "Abdichtungsarbeiten",
        "welding": "Schweißarbeiten",
    },
    "fr": {
        "concrete": "Travaux de béton",
        "drainage": "Travaux d'assainissement",
        "ductwork": "Travaux de conduits aérauliques",
        "electrical installation": "Travaux d'installation électrique",
        "facade": "Travaux de façade",
        "finishes": "Travaux de finition",
        "foundations": "Travaux de fondations",
        "lifts": "Travaux d'ascenseurs",
        "masonry": "Travaux de maçonnerie",
        "passive fire protection": "Travaux de protection passive contre l'incendie",
        "pavement": "Travaux de chaussée",
        "reinforcement": "Travaux d'armatures",
        "roofing": "Travaux de couverture",
        "steelwork": "Travaux de charpente métallique",
        "waterproofing": "Travaux d'étanchéité",
        "welding": "Travaux de soudage",
    },
}

#: The instrument behind a capture method.
CAPTURE_TEXT: dict[str, dict[str, str]] = {
    "de": {"total_station": "Tachymeter", "gnss": "GNSS-Empfänger", "laser_scan": "Laserscanner"},
    "fr": {"total_station": "Station totale", "gnss": "Récepteur GNSS", "laser_scan": "Scanner laser"},
}

#: English sentence -> translation, by language.
PHRASES: dict[str, dict[str, str]] = {
    "de": {
        # criterion characteristic
        "Pile head level deviation from design": "Höhenabweichung des Pfahlkopfs vom Entwurf",
        "Compressive strength of a cured cube specimen": "Druckfestigkeit eines ausgehärteten Würfels",
        "Nominal cover measured to the outermost bar": "Nennmaß der Betondeckung bis zum äußersten Stab",
        "Out-of-plumb of an erected column": "Lotabweichung einer montierten Stütze",
        "Effective throat thickness of a fillet weld": "Wirksame Nahtdicke einer Kehlnaht",
        "Bond strength of the applied membrane to the substrate": (
            "Haftzugfestigkeit der aufgebrachten Abdichtung auf dem Untergrund"
        ),
        "Compressive strength of a hardened mortar prism": "Druckfestigkeit eines erhärteten Mörtelprismas",
        "Maximum gap under a two metre straightedge": "Größter Spalt unter der Zwei-Meter-Richtlatte",
        "Air leakage through a fixed curtain wall bay": "Luftdurchlässigkeit eines festen Vorhangfassadenfelds",
        "Gradient of the finished roof surface": "Gefälle der fertigen Dachfläche",
        "Fall of the laid pipe run": "Gefälle der verlegten Rohrstrecke",
        "Leakage rate of a sealed duct section": "Leckluftstrom eines abgedichteten Kanalabschnitts",
        "Insulation resistance measured at 500 V d.c.": "Isolationswiderstand, gemessen bei 500 V DC",
        "Residual gap around a sealed service penetration": "Restspalt um eine abgeschottete Leitungsdurchführung",
        "Thickness of the compacted binder course": "Dicke der verdichteten Binderschicht",
        "Deviation of the guide rail from the plumb line": "Abweichung der Führungsschiene von der Lotlinie",
        # criterion method
        "Levelled against the site datum with a total station.": (
            "Mit dem Tachymeter gegen den Baustellenhöhenbezug nivelliert."
        ),
        "Three cubes cast per pour, cured and crushed at 28 days.": (
            "Drei Würfel je Betonierabschnitt hergestellt, gelagert und nach 28 Tagen geprüft."
        ),
        "Cover meter readings on a grid, plus spot checks before the pour.": (
            "Betondeckungsmessungen im Raster sowie Stichproben vor dem Betonieren."
        ),
        "Total station survey of column heads against the setting-out grid.": (
            "Tachymetermessung der Stützenköpfe gegen das Absteckraster."
        ),
        "Weld gauge on every node, with ultrasonic testing on ten per cent.": (
            "Schweißnahtlehre an jedem Knoten, Ultraschallprüfung an zehn Prozent."
        ),
        "Pull-off dolly test at the frequency stated in the specification.": (
            "Haftzugprüfung mit Prüfstempeln in der Häufigkeit der Leistungsbeschreibung."
        ),
        "Prisms cast from the mix in use and crushed at 28 days.": (
            "Prismen aus dem verwendeten Mörtel hergestellt und nach 28 Tagen geprüft."
        ),
        "Straightedge survey on a grid, with the worst reading recorded.": (
            "Richtlattenmessung im Raster, der ungünstigste Wert wird erfasst."
        ),
        "On-site chamber test on a representative bay.": "Prüfkammerversuch vor Ort an einem repräsentativen Feld.",
        "Level survey between the high point and each outlet.": "Nivellement zwischen Hochpunkt und jedem Ablauf.",
        "Invert levels surveyed at each manhole before backfill.": (
            "Sohlhöhen an jedem Schacht vor dem Verfüllen eingemessen."
        ),
        "Pressurised section test on a representative run.": (
            "Druckprüfung eines Abschnitts an einer repräsentativen Strecke."
        ),
        "Insulation resistance test on every final circuit at the board.": (
            "Isolationsmessung an jedem Endstromkreis am Verteiler."
        ),
        "Measured at every penetration before the riser is closed.": (
            "Messung an jeder Durchführung vor dem Schließen des Steigschachts."
        ),
        "Cores taken on a grid and measured.": "Bohrkerne im Raster entnommen und vermessen.",
        "Plumb line and total station survey over the full shaft height.": (
            "Lot- und Tachymetermessung über die gesamte Schachthöhe."
        ),
        # materials and suppliers
        "Ready-mixed concrete C30/37 XC4": "Transportbeton C30/37 XC4",
        "Reinforcing steel B500B": "Betonstahl B500B",
        "Structural steel sections S355JR": "Baustahlprofile S355JR",
        "Bituminous tanking membrane system": "Bituminöses Abdichtungsbahnensystem",
        "Factory-produced masonry mortar M5": "Werkmörtel für Mauerwerk M5",
        "Unitised curtain wall panels": "Elementierte Vorhangfassadenelemente",
        "Galvanised steel ductwork": "Lüftungskanäle aus verzinktem Stahl",
        "LSZH power cable, 400/230 V distribution": "Energiekabel halogenfrei (LSZH), Verteilung 400/230 V",
        "Intumescent penetration sealing system": "Dämmschichtbildendes Abschottungssystem für Durchführungen",
        "Asphalt concrete AC 16 binder course": "Asphaltbinder AC 16",
        "Ready-mixed concrete supplier": "Transportbetonlieferant",
        "Reinforcement fabricator": "Bewehrungsbiegebetrieb",
        "Structural steelwork fabricator": "Stahlbauunternehmen",
        "Waterproofing systems supplier": "Lieferant für Abdichtungssysteme",
        "Dry mortar supplier": "Trockenmörtellieferant",
        "Curtain wall systems supplier": "Lieferant für Vorhangfassaden",
        "Ductwork fabricator": "Lüftungskanalhersteller",
        "Electrical wholesaler": "Elektrogroßhandel",
        "Passive fire protection supplier": "Lieferant für baulichen Brandschutz",
        "Asphalt plant supplier": "Asphaltmischwerk",
        # as-built records
        "Pile head as-built levels, grid A-D": "Pfahlkopfhöhen, Ist-Aufmaß, Achse A-D",
        "Erected frame plumb survey, grid 4-7": "Lotmessung des montierten Tragwerks, Achse 4-7",
        "Floor flatness point cloud, levels 3 to 5": "Punktwolke zur Bodenebenheit, Ebenen 3 bis 5",
        "Roof falls as-built survey, zones 1 and 2": "Aufmaß der ausgeführten Dachgefälle, Zonen 1 und 2",
        "Drainage invert as-built survey, MH12 to MH15": "Aufmaß der ausgeführten Rohrsohlen, MH12 bis MH15",
        "Lift shaft guide rail as-built alignment, core B": (
            "Ausgeführte Ausrichtung der Führungsschienen im Aufzugsschacht, Kern B"
        ),
        # gates
        "Hold point - pile caps may not be cast before the head levels are accepted": (
            "Haltepunkt - Pfahlkopfplatten dürfen erst nach Abnahme der Kopfhöhen betoniert werden"
        ),
        "Hold point - no concrete placed before the pre-pour inspection is signed": (
            "Haltepunkt - kein Beton einbauen, bevor die Abnahme vor dem Betonieren unterzeichnet ist"
        ),
        "Hold point - reinforcement release before the slab pour": (
            "Haltepunkt - Freigabe der Bewehrung vor dem Betonieren der Decke"
        ),
        "Witness point - third-party inspector attends the weld testing": (
            "Beobachtungspunkt - Prüfer der Drittstelle nimmt an der Schweißnahtprüfung teil"
        ),
        "Hold point - no backfill before the tanking is accepted": (
            "Haltepunkt - kein Verfüllen vor Abnahme der Abdichtung"
        ),
        "Witness point - client representative attends the facade chamber test": (
            "Beobachtungspunkt - Vertreter des Auftraggebers nimmt an der Fassaden-Kammerprüfung teil"
        ),
        "Hold point - drainage runs may not be backfilled before acceptance": (
            "Haltepunkt - Entwässerungsleitungen dürfen erst nach Abnahme verfüllt werden"
        ),
        "Witness point - leakage test witnessed before the ceilings close": (
            "Beobachtungspunkt - Dichtheitsprüfung wird vor dem Schließen der Decken beobachtet"
        ),
        "Hold point - risers may not be closed before the fire stopping is accepted": (
            "Haltepunkt - Steigschächte dürfen erst nach Abnahme der Brandabschottung geschlossen werden"
        ),
        "Witness point - notified body attends the lift acceptance test": (
            "Beobachtungspunkt - benannte Stelle nimmt an der Aufzugsabnahmeprüfung teil"
        ),
        # laboratories, surveyors, issuers
        "Independent materials testing laboratory": "Unabhängiges Baustoffprüflabor",
        "Regional construction materials laboratory": "Regionales Baustofflabor",
        "Site testing laboratory (accredited)": "Baustellenlabor (akkreditiert)",
        "ISO/IEC 17025 accredited": "Akkreditiert nach ISO/IEC 17025",
        "ISO/IEC 17025 accredited (scope: construction materials)": (
            "Akkreditiert nach ISO/IEC 17025 (Umfang: Baustoffe)"
        ),
        "Site survey team (main contractor)": "Vermessungstrupp der Baustelle (Generalunternehmer)",
        "Independent setting-out surveyor": "Unabhängiger Vermessungsingenieur (Absteckung)",
        "Specialist scanning subcontractor": "Spezialunternehmen für Laserscanning",
        "Manufacturer's quality department": "Qualitätsabteilung des Herstellers",
        "Notified body (CE marking)": "Notifizierte Stelle (CE-Kennzeichnung)",
        "Independent inspection body": "Unabhängige Überwachungsstelle",
        # handover packages
        "Whole works - acceptance package": "Gesamtleistung - Abnahmepaket",
        "Sectional handover - car park and external works": "Teilabnahme - Tiefgarage und Außenanlagen",
        "Section 1: car park levels -1 and -2, external works": (
            "Abschnitt 1: Tiefgarage Ebenen -1 und -2, Außenanlagen"
        ),
    },
    "fr": {
        "Pile head level deviation from design": "Écart de niveau de la tête de pieu par rapport au projet",
        "Compressive strength of a cured cube specimen": "Résistance en compression d'un cube durci",
        "Nominal cover measured to the outermost bar": "Enrobage nominal mesuré jusqu'à la barre la plus extérieure",
        "Out-of-plumb of an erected column": "Défaut d'aplomb d'un poteau monté",
        "Effective throat thickness of a fillet weld": "Gorge utile d'un cordon d'angle",
        "Bond strength of the applied membrane to the substrate": "Adhérence de la membrane appliquée sur le support",
        "Compressive strength of a hardened mortar prism": "Résistance en compression d'un prisme de mortier durci",
        "Maximum gap under a two metre straightedge": "Écart maximal sous la règle de deux mètres",
        "Air leakage through a fixed curtain wall bay": "Perméabilité à l'air d'une trame fixe de façade-rideau",
        "Gradient of the finished roof surface": "Pente de la surface de toiture finie",
        "Fall of the laid pipe run": "Pente du tronçon de canalisation posé",
        "Leakage rate of a sealed duct section": "Débit de fuite d'un tronçon de conduit étanché",
        "Insulation resistance measured at 500 V d.c.": "Résistance d'isolement mesurée sous 500 V c.c.",
        "Residual gap around a sealed service penetration": "Jeu résiduel autour d'un passage de réseau obturé",
        "Thickness of the compacted binder course": "Épaisseur de la couche de liaison compactée",
        "Deviation of the guide rail from the plumb line": "Écart du rail de guidage par rapport au fil à plomb",
        "Levelled against the site datum with a total station.": (
            "Nivelé par rapport au repère de chantier avec une station totale."
        ),
        "Three cubes cast per pour, cured and crushed at 28 days.": (
            "Trois cubes confectionnés par plot, conservés puis écrasés à 28 jours."
        ),
        "Cover meter readings on a grid, plus spot checks before the pour.": (
            "Relevés au pachomètre sur une grille, avec contrôles ponctuels avant bétonnage."
        ),
        "Total station survey of column heads against the setting-out grid.": (
            "Levé à la station totale des têtes de poteaux par rapport à la trame d'implantation."
        ),
        "Weld gauge on every node, with ultrasonic testing on ten per cent.": (
            "Jauge de soudure sur chaque nœud, contrôle par ultrasons sur dix pour cent."
        ),
        "Pull-off dolly test at the frequency stated in the specification.": (
            "Essai d'arrachement par plot à la fréquence fixée au cahier des charges."
        ),
        "Prisms cast from the mix in use and crushed at 28 days.": (
            "Prismes confectionnés avec le mortier utilisé et écrasés à 28 jours."
        ),
        "Straightedge survey on a grid, with the worst reading recorded.": (
            "Relevé à la règle sur une grille, la pire valeur étant consignée."
        ),
        "On-site chamber test on a representative bay.": "Essai en caisson sur site sur une trame représentative.",
        "Level survey between the high point and each outlet.": "Nivellement entre le point haut et chaque évacuation.",
        "Invert levels surveyed at each manhole before backfill.": (
            "Niveaux de radier relevés à chaque regard avant remblaiement."
        ),
        "Pressurised section test on a representative run.": "Essai en pression d'un tronçon représentatif.",
        "Insulation resistance test on every final circuit at the board.": (
            "Mesure d'isolement de chaque circuit terminal au tableau."
        ),
        "Measured at every penetration before the riser is closed.": (
            "Mesuré à chaque passage avant fermeture de la gaine."
        ),
        "Cores taken on a grid and measured.": "Carottes prélevées sur une grille puis mesurées.",
        "Plumb line and total station survey over the full shaft height.": (
            "Fil à plomb et levé à la station totale sur toute la hauteur de la cage."
        ),
        "Ready-mixed concrete C30/37 XC4": "Béton prêt à l'emploi C30/37 XC4",
        "Reinforcing steel B500B": "Acier d'armature B500B",
        "Structural steel sections S355JR": "Profilés en acier de construction S355JR",
        "Bituminous tanking membrane system": "Système de cuvelage à membrane bitumineuse",
        "Factory-produced masonry mortar M5": "Mortier de maçonnerie industriel M5",
        "Unitised curtain wall panels": "Panneaux de façade-rideau préfabriqués",
        "Galvanised steel ductwork": "Conduits en acier galvanisé",
        "LSZH power cable, 400/230 V distribution": "Câble d'énergie LSZH, distribution 400/230 V",
        "Intumescent penetration sealing system": "Système d'obturation intumescent des traversées",
        "Asphalt concrete AC 16 binder course": "Enrobé bitumineux AC 16, couche de liaison",
        "Ready-mixed concrete supplier": "Fournisseur de béton prêt à l'emploi",
        "Reinforcement fabricator": "Façonnier d'armatures",
        "Structural steelwork fabricator": "Constructeur métallique",
        "Waterproofing systems supplier": "Fournisseur de systèmes d'étanchéité",
        "Dry mortar supplier": "Fournisseur de mortier sec",
        "Curtain wall systems supplier": "Fournisseur de systèmes de façade-rideau",
        "Ductwork fabricator": "Fabricant de conduits",
        "Electrical wholesaler": "Grossiste en matériel électrique",
        "Passive fire protection supplier": "Fournisseur de protection passive contre l'incendie",
        "Asphalt plant supplier": "Centrale d'enrobage",
        "Pile head as-built levels, grid A-D": "Niveaux de récolement des têtes de pieux, axes A-D",
        "Erected frame plumb survey, grid 4-7": "Relevé d'aplomb de l'ossature montée, axes 4-7",
        "Floor flatness point cloud, levels 3 to 5": "Nuage de points de planéité des sols, niveaux 3 à 5",
        "Roof falls as-built survey, zones 1 and 2": "Relevé de récolement des pentes de toiture, zones 1 et 2",
        "Drainage invert as-built survey, MH12 to MH15": (
            "Relevé de récolement des radiers d'assainissement, MH12 à MH15"
        ),
        "Lift shaft guide rail as-built alignment, core B": (
            "Alignement de récolement des guides de la cage d'ascenseur, noyau B"
        ),
        "Hold point - pile caps may not be cast before the head levels are accepted": (
            "Point d'arrêt - les chevêtres ne peuvent être bétonnés avant acceptation des niveaux de tête"
        ),
        "Hold point - no concrete placed before the pre-pour inspection is signed": (
            "Point d'arrêt - aucun béton mis en œuvre avant signature du contrôle avant bétonnage"
        ),
        "Hold point - reinforcement release before the slab pour": (
            "Point d'arrêt - validation des armatures avant bétonnage de la dalle"
        ),
        "Witness point - third-party inspector attends the weld testing": (
            "Point de surveillance - l'organisme tiers assiste aux contrôles de soudure"
        ),
        "Hold point - no backfill before the tanking is accepted": (
            "Point d'arrêt - pas de remblaiement avant réception du cuvelage"
        ),
        "Witness point - client representative attends the facade chamber test": (
            "Point de surveillance - le représentant du maître d'ouvrage assiste à l'essai en caisson de la façade"
        ),
        "Hold point - drainage runs may not be backfilled before acceptance": (
            "Point d'arrêt - les canalisations ne peuvent être remblayées avant réception"
        ),
        "Witness point - leakage test witnessed before the ceilings close": (
            "Point de surveillance - essai d'étanchéité constaté avant fermeture des plafonds"
        ),
        "Hold point - risers may not be closed before the fire stopping is accepted": (
            "Point d'arrêt - les gaines ne peuvent être fermées avant réception du calfeutrement coupe-feu"
        ),
        "Witness point - notified body attends the lift acceptance test": (
            "Point de surveillance - l'organisme notifié assiste à l'essai de réception de l'ascenseur"
        ),
        "Independent materials testing laboratory": "Laboratoire indépendant d'essais de matériaux",
        "Regional construction materials laboratory": "Laboratoire régional de matériaux de construction",
        "Site testing laboratory (accredited)": "Laboratoire de chantier (accrédité)",
        "ISO/IEC 17025 accredited": "Accrédité selon ISO/IEC 17025",
        "ISO/IEC 17025 accredited (scope: construction materials)": (
            "Accrédité selon ISO/IEC 17025 (portée : matériaux de construction)"
        ),
        "Site survey team (main contractor)": "Équipe de topographie de chantier (entreprise générale)",
        "Independent setting-out surveyor": "Géomètre indépendant (implantation)",
        "Specialist scanning subcontractor": "Sous-traitant spécialisé en scan 3D",
        "Manufacturer's quality department": "Service qualité du fabricant",
        "Notified body (CE marking)": "Organisme notifié (marquage CE)",
        "Independent inspection body": "Organisme de contrôle indépendant",
        "Whole works - acceptance package": "Ensemble des travaux - dossier de réception",
        "Sectional handover - car park and external works": "Réception partielle - parking et aménagements extérieurs",
        "Section 1: car park levels -1 and -2, external works": (
            "Tranche 1 : parking niveaux -1 et -2, aménagements extérieurs"
        ),
    },
}


def phrase(locale: str | None, text: str) -> str:
    """``text`` in the project's language, unchanged for English or an unlisted sentence."""
    return PHRASES.get(language_of(locale), {}).get(text, text)


def category_text(locale: str | None, category: str, *, head: bool = False) -> str:
    """The work category: a German or French noun, else the English code, capitalised at the head of a sentence."""
    noun = CATEGORY_TEXT.get(language_of(locale), {}).get(category)
    if noun is not None:
        return noun
    return category.capitalize() if head else category


def characteristic_text(locale: str | None, characteristic: str) -> str:
    """The characteristic as it follows "judged on": lowercased in English and French, as written in German."""
    lang = language_of(locale)
    if lang == "de":
        return characteristic
    return characteristic.lower() if lang == "en" else characteristic[:1].lower() + characteristic[1:]


def instrument_kind(locale: str | None, capture_method: str) -> str:
    """The instrument name for a capture method, in the project's language."""
    name = CAPTURE_TEXT.get(language_of(locale), {}).get(capture_method)
    return name if name is not None else capture_method.replace("_", " ").capitalize()
