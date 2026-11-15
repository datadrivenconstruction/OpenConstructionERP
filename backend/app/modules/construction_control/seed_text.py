# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""German and French wording of the non-conformance reports the construction-control demo raises.

The register itself (work packages, criteria, inspections, tests) is seeded in English. The reports it raises
are the part a reader opens next to the project's own German or French registers, so their title, location and
description follow the project language, which the same ``language_of`` rule as the rest of the demo estate
decides. English remains the default for every other language.
"""

from __future__ import annotations

from app.core.demo_locale_text import language_of

#: Wrapper sentences, language -> key -> text.
WORDING: dict[str, dict[str, str]] = {
    "en": {
        "inspection_description": "{category} works at {location}, inspected against {code} ({standard}).",
        "criterion_description": "Applies to {category} works at {location}. Judged on the {characteristic}.",
        "passed_notes": "Measured {value} {unit}, within the limits of {code}. Work accepted.",
        "reinspection_title": "Re-inspection after rework - {title}",
        "reinspection_description": "Re-inspection following the rejection recorded on {number}.",
        "material_reviewed": "Certificate and delivery documentation checked against the specification.",
        "material_pending": "Submitted for review; certificate and traceability being checked.",
        "test_description": "Specimen taken from {location} and tested to {method}, judged against {code}.",
        "test_pending": "Sample with the laboratory; result awaited.",
        "test_within": "Measured {value} {unit} against {code} (within the specified limits).",
        "test_outside": "Measured {value} {unit} against {code} (outside the specified limits).",
        "instrument": "{kind} instrument, site register no. {number}",
        "coordinate_system": "Project grid, levelled to the site datum",
        "gate_description": "Applies to {category} works at {location}. Satisfied by inspection {number} against {code}.",
        "gate_release": "Released against inspection {number}, which passed with {value} {unit} on {code}.",
        "gate_waived": "Attendance waived by agreement; the test record and photographs were accepted in place of attendance.",
        "failed_inspection": "Failed inspection {number}: {title}",
        "from_inspection": (
            "Raised from inspection {number} ({kind}). {notes} Judged against criterion {code} ({title}), "
            "standard {standard}."
        ),
        "failed_notes": (
            "Measured {value} {unit} against {code}. Work rejected; rework instructed and a re-inspection booked."
        ),
        "failed_test": "Out-of-specification test result {number}: {title}",
        "from_test": (
            "Raised from lab result {number}. Measured {value} {unit} against criterion {code} ({title}), "
            "standard {standard}, tested to {method}."
        ),
    },
    "de": {
        "inspection_description": "{category} an {location}, geprüft nach {code} ({standard}).",
        "criterion_description": "Gilt für {category} an {location}. Bewertet wird: {characteristic}.",
        "passed_notes": "Gemessen {value} {unit}, innerhalb der Grenzwerte von {code}. Leistung abgenommen.",
        "reinspection_title": "Nachprüfung nach Nacharbeit - {title}",
        "reinspection_description": "Nachprüfung nach der unter {number} festgehaltenen Ablehnung.",
        "material_reviewed": "Zeugnis und Lieferunterlagen gegen die Leistungsbeschreibung geprüft.",
        "material_pending": "Zur Prüfung vorgelegt; Zeugnis und Rückverfolgbarkeit werden geprüft.",
        "test_description": "Probe aus {location} entnommen und nach {method} geprüft, bewertet nach {code}.",
        "test_pending": "Probe liegt im Labor; Ergebnis steht aus.",
        "test_within": "Gemessen {value} {unit} gegen {code} (innerhalb der Vorgaben).",
        "test_outside": "Gemessen {value} {unit} gegen {code} (außerhalb der Vorgaben).",
        "instrument": "{kind}, Gerätenr. {number} im Baustellenregister",
        "coordinate_system": "Projektraster, höhenmäßig auf den Baustellenbezugspunkt bezogen",
        "gate_description": "Gilt für {category} an {location}. Erfüllt durch Prüfung {number} gegen {code}.",
        "gate_release": "Freigegeben auf Grundlage der Prüfung {number}, bestanden mit {value} {unit} bei {code}.",
        "gate_waived": "Teilnahme einvernehmlich erlassen; Prüfprotokoll und Fotos wurden anstelle der Anwesenheit akzeptiert.",
        "failed_inspection": "Nicht bestandene Prüfung {number}: {title}",
        "from_inspection": (
            "Aus Prüfung {number} ({kind}) entstanden. {notes} Bewertet nach Kriterium {code} ({title}), "
            "Norm {standard}."
        ),
        "failed_notes": (
            "Gemessen {value} {unit} gegen {code}. Leistung abgelehnt; Nacharbeit angeordnet und Nachprüfung angesetzt."
        ),
        "failed_test": "Prüfergebnis außerhalb der Vorgabe {number}: {title}",
        "from_test": (
            "Aus Laborergebnis {number} entstanden. Gemessen {value} {unit} gegen Kriterium {code} ({title}), "
            "Norm {standard}, geprüft nach {method}."
        ),
    },
    "fr": {
        "inspection_description": "{category} : {location}, contrôlé selon {code} ({standard}).",
        "criterion_description": "S'applique à : {category}, {location}. Critère évalué : {characteristic}.",
        "passed_notes": "Mesuré {value} {unit}, dans les limites de {code}. Ouvrage accepté.",
        "reinspection_title": "Contre-visite après reprise - {title}",
        "reinspection_description": "Contre-visite faisant suite au rejet consigné sous {number}.",
        "material_reviewed": "Certificat et documents de livraison vérifiés par rapport au cahier des charges.",
        "material_pending": "Soumis pour examen ; certificat et traçabilité en cours de vérification.",
        "test_description": "Éprouvette prélevée à {location} et essayée selon {method}, évaluée selon {code}.",
        "test_pending": "Échantillon au laboratoire ; résultat en attente.",
        "test_within": "Mesuré {value} {unit} par rapport à {code} (dans les limites spécifiées).",
        "test_outside": "Mesuré {value} {unit} par rapport à {code} (hors des limites spécifiées).",
        "instrument": "{kind}, n° {number} du registre de chantier",
        "coordinate_system": "Trame de projet, nivelée sur le repère de chantier",
        "gate_description": "S'applique à : {category}, {location}. Satisfait par le contrôle {number} selon {code}.",
        "gate_release": "Levé sur la base du contrôle {number}, conforme avec {value} {unit} pour {code}.",
        "gate_waived": "Présence levée d'un commun accord ; le procès-verbal d'essai et les photographies ont été acceptés en lieu et place.",
        "failed_inspection": "Contrôle non conforme {number} : {title}",
        "from_inspection": (
            "Issue du contrôle {number} ({kind}). {notes} Évalué selon le critère {code} ({title}), norme {standard}."
        ),
        "failed_notes": (
            "Mesuré {value} {unit} par rapport à {code}. Ouvrage rejeté ; reprise ordonnée et contre-visite programmée."
        ),
        "failed_test": "Résultat d'essai hors spécification {number} : {title}",
        "from_test": (
            "Issu du résultat d'essai {number}. Mesuré {value} {unit} par rapport au critère {code} ({title}), "
            "norme {standard}, essai selon {method}."
        ),
    },
}

#: Language -> work package key -> (location, inspection title, criterion title, lab test title or None).
PACKAGE_TEXT: dict[str, dict[str, tuple[str, str, str, str | None]]] = {
    "de": {
        "piling": (
            "Achse A-D / Bohrplattform",
            "Einmessung der Pfahlkopfplatten und Kürzen der Pfahlköpfe, Achse A-D",
            "Höhentoleranz des Pfahlkopfs nach dem Kürzen",
            None,
        ),
        "foundation_concrete": (
            "Kern B, Bodenplatte, Abschnitt 03",
            "Abnahme vor dem Betonieren, Kern B Bodenplatte Abschnitt 03",
            "Würfeldruckfestigkeit nach 28 Tagen, Klasse C30/37",
            "Würfeldruckversuch, Kern B Bodenplatte Abschnitt 03",
        ),
        "reinforcement": (
            "Ebene 1, Decke, Zone 2",
            "Bewehrungsverlegung und Betondeckung, Decke Ebene 1 Zone 2",
            "Betondeckung der Bewehrung",
            "Zugversuch an einer Bewehrungsprobe",
        ),
        "structural_steel": (
            "Achse 4-7, Ebenen 2 bis 5",
            "Stahlbaumontage und Lotvermessung, Achse 4-7",
            "Lotabweichung der Stütze über eine Geschosshöhe",
            None,
        ),
        "welding": (
            "Übergangsträger, Knotenanschlüsse",
            "Sicht- und zerstörungsfreie Schweißnahtprüfung, Knoten des Übergangsträgers",
            "Kehlnahtdicke, Bewertungsgruppe B",
            "Ultraschallprüfung einer durchgeschweißten Naht",
        ),
        "waterproofing": (
            "Kelleraußenwand, Feld 2",
            "Durchgängigkeit der Abdichtungsbahn vor dem Verfüllen, Feld 2",
            "Haftzugfestigkeit der Abdichtungsbahn",
            "Haftzugprüfung an der aufgebrachten Abdichtung",
        ),
        "blockwork": (
            "Ebene 2, Brandabschnittswände",
            "Ausführungsqualität des Mauerwerks der Brandabschnitte, Ebene 2",
            "Mörteldruckfestigkeit nach 28 Tagen, Klasse M5",
            "Druckfestigkeitsprüfung an Mörtelprismen",
        ),
        "screed": (
            "Ebenen 3 bis 5, Büroflächen",
            "Ebenheitsmessung des Estrichs, Ebenen 3 bis 5",
            "Ebenheitsabweichung unter der Zwei-Meter-Richtlatte",
            None,
        ),
        "facade": (
            "Nordfassade, Felder 5 bis 9",
            "Abnahme der Fassadenfelder, Nordfassade Felder 5 bis 9",
            "Luftdurchlässigkeit der Vorhangfassade bei 600 Pa",
            "Luftdurchlässigkeitsprüfung mit Prüfkammer vor Ort",
        ),
        "roofing": (
            "Hauptdach, Zonen 1 und 2",
            "Gefälle und Ablaufanschlüsse des Dachs, Zonen 1 und 2",
            "Gefälle der Dachabdichtung zu den Regenabläufen",
            None,
        ),
        "drainage": (
            "Außenanlagen, Haltung MH12 bis MH15",
            "Grundleitungen vor dem Verfüllen, MH12 bis MH15",
            "Freispiegelgefälle zwischen den Schächten",
            None,
        ),
        "hvac_duct": (
            "Ebene 4, Steigschacht und Deckenhohlraum",
            "Einbau und Dichtheitsprüfung der Lüftungskanäle, Ebene 4",
            "Luftleckage der Lüftungskanäle bei Prüfdruck, Klasse B",
            "Druck- und Dichtheitsprüfung eines Kanalabschnitts",
        ),
        "electrical": (
            "Ebene 2, Verteilung, Verteiler DB2-1 bis DB2-4",
            "Endprüfung der Endstromkreise, Verteilung Ebene 2",
            "Isolationswiderstand eines Endstromkreises",
            "Protokoll der Isolationswiderstandsmessung, Verteiler DB2-1 bis DB2-4",
        ),
        "fire_stopping": (
            "Kern A, Steigschacht, Ebenen 1 bis 6",
            "Brandabschottung der Leitungsdurchführungen, Kern A Steigschacht",
            "Spaltbreite an einer Leitungsabschottung",
            None,
        ),
        "asphalt": (
            "Zufahrtsstraße und Wirtschaftshof",
            "Abnahme der gebundenen Tragschicht, Zufahrtsstraße",
            "Schichtdicke der gebundenen Schicht nach Verdichtung",
            "Prüfung von Schichtdicke und Dichte an Bohrkernen",
        ),
        "lift_guides": (
            "Kern B, Aufzugsschacht, Kabinen 1 und 2",
            "Abnahme der Führungsschienenausrichtung, Kern B",
            "Abweichung der Führungsschienenausrichtung über die Schachthöhe",
            None,
        ),
    },
    "fr": {
        "piling": (
            "Axes A-D / plateforme de forage",
            "Implantation des chevêtres et recépage des pieux, axes A-D",
            "Tolérance de niveau de la tête de pieu après recépage",
            None,
        ),
        "foundation_concrete": (
            "Noyau B, radier, plot 03",
            "Contrôle avant bétonnage, noyau B radier plot 03",
            "Résistance en compression sur cube à 28 jours, classe C30/37",
            "Essai d'écrasement de cubes, noyau B radier plot 03",
        ),
        "reinforcement": (
            "Niveau 1, dalle, zone 2",
            "Pose des armatures et enrobage, dalle niveau 1 zone 2",
            "Enrobage des armatures",
            "Essai de traction sur une éprouvette d'armature",
        ),
        "structural_steel": (
            "Axes 4-7, niveaux 2 à 5",
            "Montage de la charpente métallique et relevé d'aplomb, axes 4-7",
            "Écart d'aplomb du poteau sur une hauteur d'étage",
            None,
        ),
        "welding": (
            "Poutre de transfert, assemblages des nœuds",
            "Contrôle visuel et non destructif des soudures, nœuds de la poutre de transfert",
            "Gorge des soudures d'angle, niveau de qualité B",
            "Contrôle par ultrasons d'une soudure à pleine pénétration",
        ),
        "waterproofing": (
            "Voile enterré du sous-sol, travée 2",
            "Continuité de la membrane d'étanchéité avant remblaiement, travée 2",
            "Adhérence par arrachement de la membrane",
            "Essai d'arrachement sur la membrane appliquée",
        ),
        "blockwork": (
            "Niveau 2, murs de compartimentage",
            "Qualité d'exécution de la maçonnerie de compartimentage, niveau 2",
            "Résistance en compression du mortier à 28 jours, classe M5",
            "Essai de compression sur prismes de mortier",
        ),
        "screed": (
            "Niveaux 3 à 5, plateaux de bureaux",
            "Relevé de planéité de la chape, niveaux 3 à 5",
            "Écart de planéité sous la règle de deux mètres",
            None,
        ),
        "facade": (
            "Façade nord, travées 5 à 9",
            "Réception des travées de mur-rideau, façade nord travées 5 à 9",
            "Perméabilité à l'air du mur-rideau à 600 Pa",
            "Essai de perméabilité à l'air en caisson sur site",
        ),
        "roofing": (
            "Toiture principale, zones 1 et 2",
            "Pentes et raccordements des évacuations de la toiture, zones 1 et 2",
            "Pente de la finition de toiture vers les évacuations d'eaux pluviales",
            None,
        ),
        "drainage": (
            "Aménagements extérieurs, tronçon MH12 à MH15",
            "Réseau enterré avant remblaiement, MH12 à MH15",
            "Pente gravitaire entre regards",
            None,
        ),
        "hvac_duct": (
            "Niveau 4, gaine technique et faux-plafond",
            "Pose des gaines et essai d'étanchéité, niveau 4",
            "Fuite d'air des gaines à la pression d'essai, classe B",
            "Essai de pression et d'étanchéité d'un tronçon de gaine",
        ),
        "electrical": (
            "Niveau 2, distribution, tableaux DB2-1 à DB2-4",
            "Essais finaux des circuits terminaux, distribution niveau 2",
            "Résistance d'isolement d'un circuit terminal",
            "Rapport de mesure de la résistance d'isolement, tableaux DB2-1 à DB2-4",
        ),
        "fire_stopping": (
            "Noyau A, gaine technique, niveaux 1 à 6",
            "Calfeutrement coupe-feu des traversées, gaine technique du noyau A",
            "Jeu linéaire au droit d'un calfeutrement de traversée",
            None,
        ),
        "asphalt": (
            "Voie d'accès et cour de service",
            "Réception de la couche liée de chaussée, voie d'accès",
            "Épaisseur de la couche liée après compactage",
            "Essai d'épaisseur et de densité sur carottes de chaussée",
        ),
        "lift_guides": (
            "Noyau B, cage d'ascenseur, cabines 1 et 2",
            "Réception de l'alignement des guides, noyau B",
            "Écart d'alignement des guides sur la hauteur de la cage",
            None,
        ),
    },
}


def control_text(locale: str | None, key: str, **values: object) -> str:
    """The wrapper sentence ``key`` in the project's language (English by default), filled in."""
    table = WORDING.get(language_of(locale), WORDING["en"])
    return table[key].format(**values)


def package_text(
    locale: str | None, package_key: str, *, location: str, inspection_title: str, criterion_title: str, lab_title: str
) -> tuple[str, str, str, str]:
    """The package's (location, inspection title, criterion title, lab title) in the project's language.

    The English values passed in are the default and are kept for any language or package without an entry.
    """
    row = PACKAGE_TEXT.get(language_of(locale), {}).get(package_key)
    if row is None:
        return location, inspection_title, criterion_title, lab_title
    return row[0], row[1], row[2], row[3] or lab_title
