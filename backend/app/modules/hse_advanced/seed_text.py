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
