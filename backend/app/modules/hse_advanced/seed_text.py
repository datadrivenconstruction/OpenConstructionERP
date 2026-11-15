# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""German and French findings and recommendations of the demo's incident investigations.

The investigations are written per project, next to that project's own incidents, so their prose follows the
project language (``language_of``). English remains the default for every other language.
"""

from __future__ import annotations

from app.core.demo_locale_text import language_of

#: Language -> investigation method -> (findings, recommendations).
INVESTIGATION_NOTES: dict[str, dict[str, tuple[str, str]]] = {
    "de": {
        "5_whys": (
            "Die Fünf-Warum-Kette endete bei einer Freigabe, die erteilt wurde, bevor die Prüfung vor Arbeitsbeginn "
            "unterzeichnet war.",
            "Die Unterschrift der Prüfung vor Arbeitsbeginn im Freigabeablauf zur Pflicht machen und die "
            "freigebenden Aufsichtführenden neu unterweisen.",
        ),
        "fishbone": (
            "Die Ursache-Wirkungs-Analyse legte den Schwerpunkt auf Methode und Maschine: Die Arbeitsanweisung "
            "erfasste das eingesetzte Gerät nicht.",
            "Die Arbeitsanweisung auf das tatsächlich eingesetzte Gerät umschreiben und der Kolonne neu aushändigen.",
        ),
        "timeline": (
            "Die Rekonstruktion des Ablaufs zeigte, dass der Sperrbereich wieder freigegeben wurde, bevor der Hub "
            "als abgeschlossen bestätigt war.",
            "Den Sperrbereich halten, bis der Hubverantwortliche ihn freigibt, und die Einweiser über die "
            "Änderung unterweisen.",
        ),
        "swot": (
            "Die Schutzmaßnahmen sind auf dem Papier stimmig, wurden in der Nachtschicht aber nur dünn überwacht.",
            "Den Aufsichtsplan auf die Nachtschicht ausdehnen und die Schutzmaßnahmen in einem Monat erneut "
            "auditieren.",
        ),
    },
    "fr": {
        "5_whys": (
            "La chaîne des cinq pourquoi aboutit à un permis délivré avant la signature du contrôle de prise de poste.",
            "Rendre la signature du contrôle de prise de poste bloquante dans le circuit des permis et reformer "
            "les responsables qui délivrent les permis.",
        ),
        "fishbone": (
            "L'analyse causes-effets pointe la méthode et le matériel : la fiche de tâche ne couvrait pas l'engin "
            "utilisé.",
            "Réécrire la fiche de tâche autour de l'engin réellement présent sur le chantier et la rediffuser à "
            "l'équipe.",
        ),
        "timeline": (
            "La reconstitution chronologique montre que la zone d'exclusion a été rouverte avant la confirmation de "
            "la fin du levage.",
            "Maintenir la zone d'exclusion jusqu'à la validation du chef de manœuvre et informer les "
            "signaleurs du changement.",
        ),
        "swot": (
            "Les mesures de maîtrise sont cohérentes sur le papier mais peu supervisées en équipe de nuit.",
            "Étendre le planning de supervision à l'équipe de nuit et réauditer les mesures dans un mois.",
        ),
    },
}


def investigation_notes(locale: str | None, method: str, default: tuple[str, str]) -> tuple[str, str]:
    """The (findings, recommendations) of an investigation method in the project's language."""
    return INVESTIGATION_NOTES.get(language_of(locale), {}).get(method, default)


#: Wrapper sentences of the bulk rows (JSAs, permits, talks, audits, CAPAs), language -> key -> text.
BULK_WORDING: dict[str, dict[str, str]] = {
    "en": {
        "jsa_task": "Task {n}: {task}",
        "jsa_location": "Block {block} - Level {level}",
        "jsa_step": "Step {n}",
        "jsa_controls": "Use PPE, sign work area, supervisor sign-off",
        "permit_description": "{kind} permit for routine site activity #{n}",
        "permit_location": "Zone {zone}",
        "permit_conditions": "Comply with site SOP and applicable PPE matrix.",
        "permit_closure": "Area cleared, debris removed, post-work inspection signed.",
        "talk_notes": "Talk #{n}: workforce engaged; questions noted.",
        "audit_summary": "Routine audit #{n}; six categories inspected.",
        "capa_title": "CAPA #{n}: address finding from audit",
        "capa_description": "Verify control measures, retrain crew, and report back to safety officer.",
        "capa_verification": "Verified on site walk-down.",
    },
    "de": {
        "jsa_task": "Aufgabe {n}: {task}",
        "jsa_location": "Block {block} - Ebene {level}",
        "jsa_step": "Schritt {n}",
        "jsa_controls": "PSA tragen, Arbeitsbereich kennzeichnen, Freigabe durch die Aufsicht",
        "permit_description": "Erlaubnisschein {kind} für laufende Baustellentätigkeit Nr. {n}",
        "permit_location": "Bereich {zone}",
        "permit_conditions": "Baustellenanweisung und die geltende PSA-Matrix einhalten.",
        "permit_closure": "Bereich geräumt, Abfall entfernt, Abnahmebegehung nach der Arbeit unterzeichnet.",
        "talk_notes": "Unterweisung Nr. {n}: Belegschaft eingebunden; Fragen notiert.",
        "audit_summary": "Regelaudit Nr. {n}; sechs Kategorien geprüft.",
        "capa_title": "Maßnahme Nr. {n}: Feststellung aus dem Audit beheben",
        "capa_description": "Schutzmaßnahmen überprüfen, Kolonne nachschulen und der Sicherheitsfachkraft berichten.",
        "capa_verification": "Bei der Baustellenbegehung überprüft.",
    },
    "fr": {
        "jsa_task": "Tâche {n} : {task}",
        "jsa_location": "Bloc {block} - niveau {level}",
        "jsa_step": "Étape {n}",
        "jsa_controls": "Porter les EPI, baliser la zone de travail, validation du responsable",
        "permit_description": "Permis {kind} pour l'activité courante de chantier n° {n}",
        "permit_location": "Zone {zone}",
        "permit_conditions": "Respecter la consigne de chantier et la matrice des EPI applicable.",
        "permit_closure": "Zone dégagée, gravats évacués, contrôle de fin de travaux signé.",
        "talk_notes": "Causerie n° {n} : équipe impliquée ; questions consignées.",
        "audit_summary": "Audit de routine n° {n} ; six catégories contrôlées.",
        "capa_title": "Action n° {n} : traiter la constatation de l'audit",
        "capa_description": "Vérifier les mesures de maîtrise, former à nouveau l'équipe et rendre compte au responsable sécurité.",
        "capa_verification": "Vérifié lors de la visite de chantier.",
    },
}

#: Permit type code -> name inside the permit description.
PERMIT_KIND: dict[str, dict[str, str]] = {
    "de": {
        "hot_work": "Heißarbeiten",
        "confined_space": "Arbeiten in engen Räumen",
        "work_at_height": "Arbeiten in der Höhe",
        "electrical": "Elektroarbeiten",
        "excavation": "Erdarbeiten",
        "lifting": "Hebearbeiten",
        "lockout_tagout": "Freischaltung und Sicherung",
        "other": "Sonstige Arbeiten",
    },
    "fr": {
        "hot_work": "travail par point chaud",
        "confined_space": "espace confiné",
        "work_at_height": "travail en hauteur",
        "electrical": "travaux électriques",
        "excavation": "terrassement",
        "lifting": "levage",
        "lockout_tagout": "consignation",
        "other": "travaux divers",
    },
}

#: English task, hazard and audit item -> translation.
BULK_PHRASES: dict[str, dict[str, str]] = {
    "de": {
        "Cast slab": "Decke betonieren",
        "Erect scaffold": "Gerüst aufbauen",
        "Install ductwork": "Lüftungskanäle montieren",
        "Pour foundation": "Fundament betonieren",
        "Install glazing": "Verglasung einbauen",
        "Falling object": "Herabfallende Gegenstände",
        "Pinch point": "Quetschstelle",
        "Slip hazard": "Rutschgefahr",
        "Exposed wiring": "Freiliegende Leitungen",
        "Sharp edge": "Scharfe Kante",
        "Hot surface": "Heiße Oberfläche",
        "Suspended load": "Schwebende Last",
        "PPE worn correctly": "PSA wird richtig getragen",
        "Permit on site": "Erlaubnisschein vor Ort",
        "Walkways unobstructed": "Verkehrswege frei",
        "Fire extinguishers tagged": "Feuerlöscher mit Prüfplakette",
        "Cables not damaged": "Kabel unbeschädigt",
        "MSDS available": "Sicherheitsdatenblätter vorhanden",
        "Edge protection intact": "Absturzsicherung intakt",
        "Tools inspected": "Werkzeuge geprüft",
    },
    "fr": {
        "Cast slab": "Bétonnage de la dalle",
        "Erect scaffold": "Montage de l'échafaudage",
        "Install ductwork": "Pose des conduits",
        "Pour foundation": "Coulage des fondations",
        "Install glazing": "Pose du vitrage",
        "Falling object": "Chute d'objet",
        "Pinch point": "Point de pincement",
        "Slip hazard": "Risque de glissade",
        "Exposed wiring": "Câblage apparent",
        "Sharp edge": "Arête vive",
        "Hot surface": "Surface chaude",
        "Suspended load": "Charge suspendue",
        "PPE worn correctly": "EPI portés correctement",
        "Permit on site": "Permis présent sur site",
        "Walkways unobstructed": "Circulations dégagées",
        "Fire extinguishers tagged": "Extincteurs vérifiés et étiquetés",
        "Cables not damaged": "Câbles non endommagés",
        "MSDS available": "Fiches de données de sécurité disponibles",
        "Edge protection intact": "Protections de rive intactes",
        "Tools inspected": "Outils contrôlés",
    },
}


def bulk_text(locale: str | None, key: str, **values: object) -> str:
    """A bulk-row sentence in the project's language (English by default), with ``values`` filled in."""
    table = BULK_WORDING.get(language_of(locale), BULK_WORDING["en"])
    return table[key].format(**values)


def bulk_phrase(locale: str | None, text: str) -> str:
    """A task, hazard or audit item in the project's language; unchanged for English."""
    return BULK_PHRASES.get(language_of(locale), {}).get(text, text)


def permit_kind(locale: str | None, permit_type: str) -> str:
    """The permit type as it reads inside a description: English ``Hot Work``, else the translated name."""
    name = PERMIT_KIND.get(language_of(locale), {}).get(permit_type)
    return name if name is not None else permit_type.replace("_", " ").title()
