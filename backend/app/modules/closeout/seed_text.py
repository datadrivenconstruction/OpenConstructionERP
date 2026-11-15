# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""German and French titles of the closeout dossier slots the demo seeds, keyed by the English title."""

from __future__ import annotations

from app.core.demo_locale_text import language_of

PHRASES: dict[str, dict[str, str]] = {
    "de": {
        "Handover & Closeout Package": "Übergabe- und Abschlusspaket",
        "As-built drawing set": "Bestandspläne (Revisionsunterlagen)",
        "O&M manual": "Betriebs- und Wartungshandbuch",
        "Warranties and guarantees": "Gewährleistungen und Garantien",
        "COBie / asset register": "COBie / Anlagenverzeichnis",
        "Punch list closure evidence": "Nachweise zur Mängelbeseitigung",
        "Final inspection certificate": "Bescheinigung der Schlussabnahme",
        "Health & safety file": "Sicherheits- und Gesundheitsschutzunterlagen",
        "Test and commissioning certificates": "Prüf- und Inbetriebnahmeprotokolle",
        "Signed acceptance certificate": "Unterzeichnetes Abnahmeprotokoll",
        "Energy performance certificate": "Energieausweis",
        "Geotechnical and survey records": "Baugrund- und Vermessungsunterlagen",
        "FM asset dataset": "FM-Datensatz der Anlagen",
        "Operator training records": "Schulungsnachweise für das Betriebspersonal",
        "Authority acceptance certificates": "Abnahmebescheinigungen der Behörden",
        "As-built drawings - mechanical and electrical": "Bestandspläne - Technische Gebäudeausrüstung",
        "As-built drawings - structural": "Bestandspläne - Tragwerk",
        "O&M manual - building services": "Betriebs- und Wartungshandbuch - Gebäudetechnik",
        "Spare parts and consumables schedule": "Verzeichnis der Ersatzteile und Verbrauchsmaterialien",
        "Warranty register with start and expiry dates": "Gewährleistungsregister mit Beginn und Ablauf",
        "Statutory certificates - electrical, gas and lifting": (
            "Gesetzliche Prüfbescheinigungen - Elektro, Gas und Hebeanlagen"
        ),
        "Fire strategy and fire stopping record": "Brandschutzkonzept und Nachweis der Brandabschottungen",
        "Test and balancing certificates": "Prüf- und Abgleichprotokolle (Hydraulik und Luftmengen)",
        "Keys, access cards and lock suite register": "Verzeichnis der Schlüssel, Zutrittskarten und Schließanlage",
        "Federated BIM model issued for record": "Koordiniertes BIM-Modell als Bestandsmodell übergeben",
        "Waste transfer and site clearance notes": "Entsorgungsnachweise und Baustellenräumung",
    },
    "fr": {
        "Handover & Closeout Package": "Dossier de remise et de clôture",
        "As-built drawing set": "Dossier des ouvrages exécutés (plans de récolement)",
        "O&M manual": "Manuel d'exploitation et de maintenance",
        "Warranties and guarantees": "Garanties et assurances",
        "COBie / asset register": "COBie / registre des actifs",
        "Punch list closure evidence": "Preuves de levée des réserves",
        "Final inspection certificate": "Certificat de visite finale",
        "Health & safety file": "Dossier d'intervention ultérieure sur l'ouvrage (DIUO)",
        "Test and commissioning certificates": "Procès-verbaux d'essais et de mise en service",
        "Signed acceptance certificate": "Procès-verbal de réception signé",
        "Energy performance certificate": "Diagnostic de performance énergétique",
        "Geotechnical and survey records": "Dossiers géotechniques et topographiques",
        "FM asset dataset": "Jeu de données d'actifs pour l'exploitation",
        "Operator training records": "Attestations de formation des exploitants",
        "Authority acceptance certificates": "Attestations de conformité des autorités",
        "As-built drawings - mechanical and electrical": "Plans de récolement - lots techniques",
        "As-built drawings - structural": "Plans de récolement - structure",
        "O&M manual - building services": "Manuel d'exploitation et de maintenance - lots techniques",
        "Spare parts and consumables schedule": "Liste des pièces de rechange et consommables",
        "Warranty register with start and expiry dates": "Registre des garanties avec dates de début et d'échéance",
        "Statutory certificates - electrical, gas and lifting": (
            "Attestations réglementaires - électricité, gaz et appareils de levage"
        ),
        "Fire strategy and fire stopping record": "Stratégie incendie et suivi du calfeutrement coupe-feu",
        "Test and balancing certificates": "Procès-verbaux d'essais et d'équilibrage",
        "Keys, access cards and lock suite register": "Registre des clés, badges d'accès et organigramme de clés",
        "Federated BIM model issued for record": "Maquette BIM fédérée remise pour archivage",
        "Waste transfer and site clearance notes": "Bordereaux de déchets et remise en état du chantier",
    },
}


def closeout_text(locale: str | None, text: str) -> str:
    """``text`` in the project's language; English and unlisted text pass through unchanged."""
    return PHRASES.get(language_of(locale), {}).get(text, text)
