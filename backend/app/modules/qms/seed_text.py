# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""German and French wording of the QMS demo rows, keyed by the exact English sentence the seeder writes.

The cleanup in ``seed.py`` matches seeded rows against the English text and every translation below, so a
row written in the project's language is still recognised as the seed's own.
"""

from __future__ import annotations

from app.core.demo_locale_text import language_of

#: Languages the seeder can write in.
LANGUAGES: tuple[str, ...] = ("en", "de", "fr")

PHRASES: dict[str, dict[str, str]] = {
    "de": {
        "Concrete pour - slab on grade": "Betonieren - Bodenplatte",
        "Formwork inspection": "Schalungsabnahme",
        "Rebar inspection": "Bewehrungsabnahme",
        "Pre-pour clean-up": "Reinigung vor dem Betonieren",
        "Slump test": "Konsistenzprüfung (Setzmaß)",
        "Cube sampling": "Würfelentnahme",
        "Per project specification": "Gemäß Leistungsbeschreibung des Projekts",
        "per pour": "je Betonierabschnitt",
        "visual / measurement": "Sichtprüfung / Messung",
        "No defects observed": "Keine Mängel festgestellt",
        "Grid A1-A4": "Achse A1-A4",
        "All formwork ties correctly torqued.": "Alle Schalungsanker korrekt angezogen.",
        "Cover blocks below 25mm in section.": "Abstandhalter im Abschnitt unter 25 mm.",
        "Awaiting re-cleanup of joint surface.": "Erneute Reinigung der Fugenfläche steht aus.",
        "Cover below spec": "Betondeckung unter Vorgabe",
        "Rebar cover < 25mm in slab section A2.": "Betondeckung der Bewehrung < 25 mm im Deckenabschnitt A2.",
        "Concrete strength below 28-day target": "Betondruckfestigkeit unter dem 28-Tage-Ziel",
        "Cube test 23MPa vs spec 30MPa - remediation required.": (
            "Würfeldruckversuch 23 MPa gegenüber 30 MPa laut Vorgabe - Nachbesserung erforderlich."
        ),
        "Supplier batch error": "Chargenfehler des Lieferanten",
        "Wall paint scuff in lobby": "Farbabschürfung an der Wand im Foyer",
        "Door latch sticks 03-12": "Türschloss klemmt 03-12",
        "HVAC noise in 04-08": "Geräusche der Lüftungsanlage in 04-08",
        "Outlet misalignment 02-04": "Steckdose schief eingebaut 02-04",
        "Crack in slab corner": "Riss in der Deckenecke",
        "Window seal gap 05-10": "Fuge an der Fensterdichtung 05-10",
        "Door hinge stiff 02-15": "Türband schwergängig 02-15",
        "Closeout: rework verified": "Abschluss: Nacharbeit geprüft",
        "QMS process audit Q2": "QM-Prozessaudit 2. Quartal",
        "Record retention period inconsistent": "Aufbewahrungsfristen für Aufzeichnungen uneinheitlich",
        "Internal audit interval drifted": "Intervall der internen Audits nicht eingehalten",
        "Non-conforming output controls weak": "Lenkung nichtkonformer Ergebnisse unzureichend",
        "See CAPA register": "Siehe Maßnahmenregister",
    },
    "fr": {
        "Concrete pour - slab on grade": "Bétonnage - dallage sur terre-plein",
        "Formwork inspection": "Contrôle du coffrage",
        "Rebar inspection": "Contrôle des armatures",
        "Pre-pour clean-up": "Nettoyage avant bétonnage",
        "Slump test": "Essai d'affaissement",
        "Cube sampling": "Prélèvement d'éprouvettes cubiques",
        "Per project specification": "Selon le cahier des charges du projet",
        "per pour": "par plot de bétonnage",
        "visual / measurement": "visuel / mesure",
        "No defects observed": "Aucun défaut constaté",
        "Grid A1-A4": "Axes A1-A4",
        "All formwork ties correctly torqued.": "Tous les tirants de coffrage sont correctement serrés.",
        "Cover blocks below 25mm in section.": "Cales d'enrobage inférieures à 25 mm dans la section.",
        "Awaiting re-cleanup of joint surface.": "Nouveau nettoyage de la surface du joint en attente.",
        "Cover below spec": "Enrobage inférieur à la spécification",
        "Rebar cover < 25mm in slab section A2.": "Enrobage des armatures < 25 mm dans la section de dalle A2.",
        "Concrete strength below 28-day target": "Résistance du béton inférieure à l'objectif à 28 jours",
        "Cube test 23MPa vs spec 30MPa - remediation required.": (
            "Essai sur cubes 23 MPa pour 30 MPa spécifiés - remise en conformité requise."
        ),
        "Supplier batch error": "Erreur de lot du fournisseur",
        "Wall paint scuff in lobby": "Éraflure de peinture au mur du hall",
        "Door latch sticks 03-12": "Loquet de porte qui coince 03-12",
        "HVAC noise in 04-08": "Bruit de CVC en 04-08",
        "Outlet misalignment 02-04": "Prise mal alignée 02-04",
        "Crack in slab corner": "Fissure à l'angle de la dalle",
        "Window seal gap 05-10": "Jeu du joint de fenêtre 05-10",
        "Door hinge stiff 02-15": "Charnière de porte dure 02-15",
        "Closeout: rework verified": "Clôture : reprise vérifiée",
        "QMS process audit Q2": "Audit des processus QMS, T2",
        "Record retention period inconsistent": "Durées de conservation des enregistrements incohérentes",
        "Internal audit interval drifted": "Intervalle des audits internes dépassé",
        "Non-conforming output controls weak": "Maîtrise des sorties non conformes insuffisante",
        "See CAPA register": "Voir le registre des actions correctives",
    },
}


def qms_text(locale: str | None, text: str) -> str:
    """``text`` in the project's language; English and unlisted text pass through unchanged."""
    return PHRASES.get(language_of(locale), {}).get(text, text)
