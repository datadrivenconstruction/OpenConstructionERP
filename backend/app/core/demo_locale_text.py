# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""Per-language wording of the demo estate's generic and hand-written project rows.

Two tables, both keyed by the project locale's language, English being the default:

* ``GENERATED_TEXT`` holds the sentences the generic row generator builds around a project's own trades and
  firms (tasks, meetings, safety, punch list, site reports, ...). Placeholders are filled by
  :func:`generated_text`.
* ``PHRASES`` maps the English sentences that hand-written demo rows still carry to their translation, so a
  German or French project never shows English prose. :func:`localise` applies it to a row of any shape.

Amounts, dates, codes and identifiers never pass through here, only prose.
"""

from __future__ import annotations

from typing import Any

#: Languages that have a table; any other project language reads the English default.
LOCALISED_LANGUAGES: tuple[str, ...] = ("de", "fr")

# key: (English, German, French)
_ROWS: dict[str, tuple[str, str, str]] = {
    # ── shared fallbacks ─────────────────────────────────────────────────
    "general_works": ("General works", "Allgemeine Bauleistungen", "Travaux généraux"),
    "works": ("Works", "Bauleistungen", "Travaux"),
    "the_works": ("the works", "Bauleistungen", "travaux"),
    "site": ("Site", "Baustelle", "Chantier"),
    "general": ("General", "Allgemein", "Général"),
    "the_main_contractor": ("the main contractor", "Generalunternehmer", "l'entreprise générale"),
    "the_building_authority": ("the building authority", "Bauaufsichtsbehörde", "l'autorité d'urbanisme"),
    # ── contacts ─────────────────────────────────────────────────────────
    "contact_client_name": ("{proj} Client", "Auftraggeber {proj}", "Maître d'ouvrage {proj}"),
    "contact_client_first": ("Project", "Auftraggeber", "Maître d'ouvrage"),
    "contact_client_last": ("Owner", "Vertretung", "Représentant"),
    "contact_client_notes": (
        "Client / employer representative",
        "Vertretung des Auftraggebers",
        "Représentant du maître d'ouvrage",
    ),
    "contact_architect_name": ("Lead Architects", "Generalplaner Architektur", "Architectes mandataires"),
    "contact_architect_first": ("Lead", "Leitender", "Architecte"),
    "contact_architect_last": ("Architect", "Architekt", "mandataire"),
    "contact_architect_notes": ("Architect of record", "Objektplanung Architektur", "Architecte mandataire"),
    "contact_structural_name": (
        "Structural Engineering Partners",
        "Tragwerksplaner Partner",
        "Bureau d'études structure",
    ),
    "contact_structural_first": ("Structural", "Fachplaner", "Ingénieur"),
    "contact_structural_last": ("Engineer", "Tragwerk", "Structure"),
    "contact_structural_notes": ("Structural engineer", "Tragwerksplanung", "Ingénieur structure"),
    "contact_mep_first": ("MEP", "Fachplaner", "Ingénieur"),
    "contact_mep_last": ("Engineer", "TGA", "Fluides"),
    "contact_mep_notes": (
        "MEP / building services engineer",
        "Fachplanung Technische Gebäudeausrüstung (TGA)",
        "Bureau d'études fluides et CVC",
    ),
    "contact_qs_first": ("Quantity", "Kostenplanung", "Économiste"),
    "contact_qs_last": ("Surveyor", "Mengenermittlung", "de la construction"),
    "contact_qs_notes": (
        "Cost consultant / quantity surveyor",
        "Kostenplanung und Mengenermittlung",
        "Économiste de la construction",
    ),
    "contact_contractor_name": ("Principal Contractor", "Generalunternehmer", "Entreprise générale"),
    "contact_contractor_first": ("Project", "Projektleitung", "Directeur"),
    "contact_contractor_last": ("Director", "Bauausführung", "de projet"),
    "contact_contractor_notes": ("Main contractor", "Generalunternehmer", "Entreprise générale"),
    "contact_sub_first": ("Site", "Bauleitung", "Conducteur"),
    "contact_sub_last": ("Manager", "Nachunternehmer", "de travaux"),
    "contact_sub_notes": ("{trade} subcontractor", "Nachunternehmer {trade}", "Sous-traitant {trade}"),
    "contact_authority_name": (
        "{city} Building Control Office",
        "Bauaufsichtsamt {city}",
        "Service d'urbanisme de {city}",
    ),
    "contact_authority_name_default": (
        "Local Building Control Office",
        "Örtliches Bauaufsichtsamt",
        "Service local d'urbanisme",
    ),
    "contact_authority_first": ("Building", "Sachbearbeitung", "Inspecteur"),
    "contact_authority_last": ("Inspector", "Bauaufsicht", "du bâtiment"),
    "contact_authority_notes": (
        "Permitting and inspection authority",
        "Genehmigungs- und Prüfbehörde",
        "Autorité d'autorisation et de contrôle",
    ),
    # ── tasks ────────────────────────────────────────────────────────────
    "task_0": (
        "Mobilise site and establish welfare facilities",
        "Baustelle einrichten und Sozialeinrichtungen herstellen",
        "Installation de chantier et mise en place des locaux de vie",
    ),
    "task_1": (
        "Confirm building permit / authority approvals",
        "Baugenehmigung und behördliche Freigaben bestätigen",
        "Confirmer le permis de construire et les accords des autorités",
    ),
    "task_2": (
        "Issue procurement schedule for long-lead items",
        "Beschaffungsplan für Bauteile mit langer Lieferzeit herausgeben",
        "Émettre le calendrier d'approvisionnement des éléments à long délai",
    ),
    "task_3": (
        "Set up document control and CDE structure",
        "Dokumentenlenkung und CDE-Struktur einrichten",
        "Mettre en place la gestion documentaire et la structure du CDE",
    ),
    "task_4": (
        "Baseline programme review with main contractor",
        "Basisterminplan mit dem Generalunternehmer prüfen",
        "Revue du planning de référence avec l'entreprise générale",
    ),
    "task_5": (
        "Health & safety induction plan",
        "Einweisungskonzept Arbeitssicherheit",
        "Plan d'accueil santé et sécurité",
    ),
    "task_6": (
        "Quality control plan and inspection hold-points",
        "Qualitätsprüfplan und Haltepunkte",
        "Plan de contrôle qualité et points d'arrêt",
    ),
    "task_7": (
        "Coordinate temporary works design",
        "Planung der Hilfskonstruktionen koordinieren",
        "Coordonner l'étude des ouvrages provisoires",
    ),
    "task_8": (
        "Submit insurance and bonds to client",
        "Versicherungen und Bürgschaften beim Auftraggeber einreichen",
        "Remettre les assurances et cautions au maître d'ouvrage",
    ),
    "task_9": (
        "Agree progress claim / valuation cycle",
        "Rhythmus der Abschlagsrechnungen vereinbaren",
        "Convenir du rythme des situations de travaux",
    ),
    "task_description": ("{title} for {proj}.", "{title} für {proj}.", "{title} pour {proj}."),
    # ── RFIs ─────────────────────────────────────────────────────────────
    "rfi_scope": ("scope", "Leistungsumfang", "périmètre"),
    "rfi_subject": (
        "{trade} - clarification on {item}",
        "{trade} - Klärung zu {item}",
        "{trade} - précision sur {item}",
    ),
    "rfi_question": (
        "Please clarify the detail for '{item}' in section {code}. Coordination required with {firm} before "
        "procurement.",
        "Bitte das Detail zu '{item}' in Abschnitt {code} klären. Abstimmung mit {firm} vor der Vergabe erforderlich.",
        "Merci de préciser le détail de « {item} » dans la section {code}. Coordination nécessaire avec {firm} "
        "avant l'attribution.",
    ),
    "rfi_response": (
        "Confirmed approach for {trade}. Revised detail issued to {firm}.",
        "Vorgehen für {trade} bestätigt. Überarbeitetes Detail an {firm} übermittelt.",
        "Approche confirmée pour {trade}. Détail révisé transmis à {firm}.",
    ),
    # ── meetings ─────────────────────────────────────────────────────────
    "meeting_0": ("Project kick-off meeting", "Bauanlaufbesprechung", "Réunion de lancement du projet"),
    "meeting_1": (
        "Weekly progress meeting #1",
        "Wochenbesprechung Nr. 1",
        "Réunion de chantier hebdomadaire n° 1",
    ),
    "meeting_2": (
        "Design coordination workshop",
        "Planungskoordinierungs-Workshop",
        "Atelier de coordination de la conception",
    ),
    "meeting_3": (
        "Weekly progress meeting #2",
        "Wochenbesprechung Nr. 2",
        "Réunion de chantier hebdomadaire n° 2",
    ),
    "meeting_4": (
        "Commercial / cost review",
        "Kaufmännische Besprechung / Kostenprüfung",
        "Revue commerciale et des coûts",
    ),
    "meeting_agenda_0": (
        "Programme and progress review",
        "Terminplan und Baufortschritt",
        "Revue du planning et de l'avancement",
    ),
    "meeting_agenda_1": ("{trade} update", "Stand {trade}", "Point d'avancement {trade}"),
    "meeting_agenda_2": (
        "HSE and quality status",
        "Stand Arbeitssicherheit und Qualität",
        "Point sécurité et qualité",
    ),
    "meeting_location": ("Site office", "Baubüro", "Bureau de chantier"),
    "meeting_action": (
        "Distribute minutes and update action log",
        "Protokoll verteilen und Maßnahmenliste aktualisieren",
        "Diffuser le compte rendu et mettre à jour le suivi des actions",
    ),
    "meeting_minutes": (
        "Progress on track; actions assigned.",
        "Baufortschritt im Plan; Maßnahmen zugewiesen.",
        "Avancement conforme au planning ; actions attribuées.",
    ),
    "meeting_attendee": ("{company} rep", "Vertreter {company}", "Représentant {company}"),
    # ── safety incidents (title, root cause) ─────────────────────────────
    "incident_0": (
        "Near miss - material fell from height",
        "Beinaheunfall - Material aus der Höhe herabgefallen",
        "Presque-accident - chute de matériau en hauteur",
    ),
    "incident_cause_0": ("Edge protection gap", "Lücke im Seitenschutz", "Garde-corps incomplet"),
    "incident_1": (
        "Minor hand laceration during handling",
        "Leichte Schnittverletzung an der Hand beim Handling",
        "Coupure légère à la main lors de la manutention",
    ),
    "incident_cause_1": (
        "Cut-resistant gloves not worn",
        "Schnittschutzhandschuhe nicht getragen",
        "Gants anti-coupures non portés",
    ),
    "incident_2": (
        "Plant / pedestrian near miss in laydown area",
        "Beinaheunfall zwischen Baumaschine und Fußgänger im Lagerbereich",
        "Presque-accident engin / piéton sur l'aire de stockage",
    ),
    "incident_cause_2": (
        "Segregation not enforced",
        "Trennung der Verkehrswege nicht durchgesetzt",
        "Séparation des circulations non respectée",
    ),
    "incident_3": (
        "Temporary services strike during excavation",
        "Beschädigung einer provisorischen Leitung beim Aushub",
        "Endommagement d'un réseau provisoire lors des terrassements",
    ),
    "incident_cause_3": (
        "Service scan not refreshed",
        "Leitungsortung nicht aktualisiert",
        "Détection des réseaux non actualisée",
    ),
    "incident_4": (
        "Load swung outside the exclusion zone during a lift",
        "Last schwenkte beim Hub aus dem Sperrbereich",
        "Charge déviée hors de la zone d'exclusion pendant un levage",
    ),
    "incident_cause_4": (
        "Lift plan not re-briefed after the crane moved",
        "Hubplan nach dem Umsetzen des Krans nicht erneut unterwiesen",
        "Plan de levage non rappelé après le déplacement de la grue",
    ),
    "incident_5": (
        "Eye irritation from airborne dust",
        "Augenreizung durch Staub in der Luft",
        "Irritation oculaire due aux poussières en suspension",
    ),
    "incident_cause_5": (
        "Water suppression not connected before cutting",
        "Wasserbindung vor dem Schneiden nicht angeschlossen",
        "Abattage des poussières à l'eau non raccordé avant la coupe",
    ),
    "incident_6": (
        "Stacked materials toppled in high wind",
        "Gestapeltes Material bei starkem Wind umgestürzt",
        "Chute de matériaux empilés par vent fort",
    ),
    "incident_cause_6": (
        "Stack height above the method statement limit",
        "Stapelhöhe über der Grenze der Arbeitsanweisung",
        "Hauteur de stockage supérieure à la limite du mode opératoire",
    ),
    "incident_7": (
        "Silt-laden runoff reached the site drain",
        "Schlammhaltiges Abwasser gelangte in die Baustellenentwässerung",
        "Eaux de ruissellement chargées de boue dans le réseau du chantier",
    ),
    "incident_cause_7": (
        "Bunding not reinstated after the pour",
        "Auffangwanne nach dem Betonieren nicht wiederhergestellt",
        "Rétention non remise en place après le bétonnage",
    ),
    "incident_8": (
        "Slip on a wet access ramp",
        "Ausrutschen auf nasser Zugangsrampe",
        "Glissade sur une rampe d'accès mouillée",
    ),
    "incident_cause_8": (
        "Ramp left uncovered after the wash-down",
        "Rampe nach der Reinigung nicht abgedeckt",
        "Rampe laissée sans protection après le nettoyage",
    ),
    "incident_9": (
        "Smouldering waste bin beside hot works",
        "Schwelender Abfallbehälter neben Heißarbeiten",
        "Benne à déchets couvante près de travaux par points chauds",
    ),
    "incident_cause_9": (
        "Fire watch stood down before the cooling period ended",
        "Brandwache vor Ende der Nachlaufzeit abgezogen",
        "Surveillance incendie levée avant la fin du délai de refroidissement",
    ),
    "incident_10": (
        "Scaffold board dislodged underfoot",
        "Gerüstbohle unter dem Fuß verrutscht",
        "Plancher d'échafaudage déplacé sous le pied",
    ),
    "incident_cause_10": (
        "Board not clipped after an inspection",
        "Bohle nach einer Kontrolle nicht gesichert",
        "Plancher non bloqué après un contrôle",
    ),
    "incident_location": ("{trade} area", "Bereich {trade}", "Zone {trade}"),
    "incident_description": (
        "{title} during {trade}.",
        "{title} bei {trade}.",
        "{title} pendant les travaux de {trade}.",
    ),
    "incident_action_done": (
        "Toolbox talk and re-brief affected crew",
        "Kurzunterweisung und erneute Einweisung der betroffenen Kolonne",
        "Causerie sécurité et nouveau briefing de l'équipe concernée",
    ),
    "incident_action_open": (
        "Investigation under way, actions to follow",
        "Untersuchung läuft, Maßnahmen folgen",
        "Enquête en cours, actions à suivre",
    ),
    # ── safety observations ──────────────────────────────────────────────
    "observation_0": (
        "Scaffold handrail incomplete on working platform",
        "Gerüstgeländer an der Arbeitsplattform unvollständig",
        "Garde-corps d'échafaudage incomplet sur la plateforme de travail",
    ),
    "observation_1": (
        "Operative without eye protection during cutting",
        "Mitarbeiter ohne Augenschutz beim Trennschneiden",
        "Ouvrier sans protection oculaire pendant la découpe",
    ),
    "observation_2": (
        "Access route partially blocked by stored materials",
        "Zugangsweg teilweise durch gelagertes Material blockiert",
        "Voie d'accès partiellement obstruée par des matériaux stockés",
    ),
    "observation_3": (
        "Unprotected slab edge at leading edge of works",
        "Ungesicherte Deckenkante an der Arbeitskante",
        "Rive de dalle non protégée en front de travaux",
    ),
    "observation_4": (
        "Dust generation during dry cutting",
        "Staubentwicklung beim Trockenschneiden",
        "Émission de poussières lors de la coupe à sec",
    ),
    "observation_5": (
        "Good practice - full PPE and clean work area observed",
        "Gute Praxis - vollständige PSA und saubere Arbeitsbereiche festgestellt",
        "Bonne pratique - EPI complets et zone de travail propre constatés",
    ),
    "observation_location": ("{trade} zone", "Bereich {trade}", "Zone {trade}"),
    "observation_immediate": (
        "Corrected on the spot",
        "Vor Ort sofort behoben",
        "Corrigé immédiatement sur place",
    ),
    "observation_corrective_done": (
        "Re-brief crew and add to inspection checklist",
        "Kolonne erneut unterweisen und in die Prüfliste aufnehmen",
        "Rappeler les consignes à l'équipe et ajouter au contrôle",
    ),
    "observation_corrective_open": (
        "Awaiting re-inspection before the entry can be closed",
        "Nachkontrolle steht aus, bevor der Eintrag geschlossen werden kann",
        "Contre-visite en attente avant la clôture de la fiche",
    ),
    # ── quality inspections ──────────────────────────────────────────────
    "inspection_title": ("{trade} inspection", "Prüfung {trade}", "Contrôle {trade}"),
    "inspection_description": (
        "Hold-point inspection for {item} (section {code}).",
        "Haltepunktprüfung für {item} (Abschnitt {code}).",
        "Contrôle sur point d'arrêt pour {item} (section {code}).",
    ),
    "inspection_location": ("{trade} area", "Bereich {trade}", "Zone {trade}"),
    "inspection_cat_0": ("Pre-work", "Vorbereitung", "Travaux préparatoires"),
    "inspection_cat_1": ("Workmanship", "Ausführung", "Exécution"),
    "inspection_cat_2": ("Records", "Dokumentation", "Enregistrements"),
    "inspection_q_0": (
        "Approved materials on site?",
        "Freigegebene Materialien auf der Baustelle?",
        "Matériaux approuvés sur site ?",
    ),
    "inspection_q_1": (
        "Work to specification?",
        "Ausführung nach Leistungsbeschreibung?",
        "Travaux conformes au descriptif ?",
    ),
    "inspection_q_2": (
        "Test records complete?",
        "Prüfprotokolle vollständig?",
        "Procès-verbaux d'essais complets ?",
    ),
    # ── invoices ─────────────────────────────────────────────────────────
    "invoice_notes": (
        "{firm} - interim valuation, {trade}",
        "{firm} - Abschlagsrechnung, {trade}",
        "{firm} - situation de travaux, {trade}",
    ),
    "invoice_line": (
        "{item} - works to date",
        "{item} - Leistungen bis zum Stichtag",
        "{item} - travaux réalisés à ce jour",
    ),
    "invoice_receivable_line": (
        "Interim application for works executed to date",
        "Abschlagsrechnung für die bisher erbrachten Leistungen",
        "Demande de paiement intermédiaire pour les travaux réalisés à ce jour",
    ),
    # ── punch list ───────────────────────────────────────────────────────
    "punch_0": (
        "Touch-up required to finished surface",
        "Ausbesserung der fertigen Oberfläche erforderlich",
        "Retouche de la surface finie à réaliser",
    ),
    "punch_1": (
        "Sealant defect at junction to be redone",
        "Mangelhafte Fugenabdichtung am Anschluss neu herstellen",
        "Défaut de joint d'étanchéité à la jonction à refaire",
    ),
    "punch_2": (
        "Minor crack to be monitored / filled",
        "Kleiner Riss beobachten / verfüllen",
        "Fissure mineure à surveiller / reboucher",
    ),
    "punch_3": (
        "Service penetration not fully sealed",
        "Leitungsdurchführung nicht vollständig abgedichtet",
        "Traversée de réseau non entièrement calfeutrée",
    ),
    "punch_4": (
        "Fixing/bracket missing - to be installed",
        "Befestigung/Halterung fehlt - nachrüsten",
        "Fixation / support manquant - à installer",
    ),
    "punch_5": (
        "Damaged finish to be replaced",
        "Beschädigte Oberfläche ersetzen",
        "Finition endommagée à remplacer",
    ),
    "punch_6": (
        "Snag - door/ironmongery adjustment",
        "Mangel - Tür/Beschlag nachjustieren",
        "Réserve - réglage de porte / quincaillerie",
    ),
    "punch_7": (
        "Leak at connection - retighten and test",
        "Undichtigkeit am Anschluss - nachziehen und prüfen",
        "Fuite au raccord - resserrer et tester",
    ),
    "punch_8": (
        "Alignment/level out of tolerance",
        "Flucht/Höhenlage außerhalb der Toleranz",
        "Alignement / niveau hors tolérance",
    ),
    "punch_9": (
        "Cleaning required before handover",
        "Reinigung vor der Übergabe erforderlich",
        "Nettoyage nécessaire avant la réception",
    ),
    "punch_10": (
        "Paint defect on wall surface",
        "Anstrichmangel an der Wandfläche",
        "Défaut de peinture sur le mur",
    ),
    "punch_11": (
        "Missing label / signage",
        "Beschriftung / Beschilderung fehlt",
        "Étiquette / signalétique manquante",
    ),
    "punch_12": (
        "Tile lippage exceeds tolerance",
        "Fliesenversatz überschreitet die Toleranz",
        "Désaffleurement de carrelage hors tolérance",
    ),
    "punch_13": (
        "Loose handrail fixing",
        "Handlauf-Befestigung locker",
        "Fixation de main courante desserrée",
    ),
    "punch_14": (
        "Incomplete grout to wet area",
        "Unvollständige Verfugung im Nassbereich",
        "Jointoiement incomplet en zone humide",
    ),
    "punch_description": ("{title} - {trade}.", "{title} - {trade}.", "{title} - {trade}."),
    "punch_resolution": (
        "Rectified and re-checked",
        "Nachgebessert und erneut geprüft",
        "Repris et recontrôlé",
    ),
    # ── site reports ─────────────────────────────────────────────────────
    "field_work": (
        "{trade} progressing as planned. Materials delivered and inspected.",
        "{trade} läuft planmäßig. Material geliefert und geprüft.",
        "{trade} se déroule conformément au planning. Matériaux livrés et contrôlés.",
    ),
    "field_labour": ("General labor", "Hilfskräfte", "Main-d'œuvre générale"),
    "field_equipment_0": ("Tower crane", "Turmdrehkran", "Grue à tour"),
    "field_equipment_1": ("Telehandler", "Teleskoplader", "Chariot télescopique"),
    "field_equipment_2": ("Excavator", "Bagger", "Pelle hydraulique"),
    "field_delay": (
        "Weather delay - works paused",
        "Witterungsbedingte Verzögerung - Arbeiten unterbrochen",
        "Retard dû aux intempéries - travaux interrompus",
    ),
    # ── non-conformance reports ──────────────────────────────────────────
    "ncr_cause_0": (
        "Work not executed to specification",
        "Leistung nicht gemäß Leistungsbeschreibung ausgeführt",
        "Ouvrage non exécuté conformément au descriptif",
    ),
    "ncr_cause_1": (
        "Non-conforming material delivered to site",
        "Nicht konformes Material auf die Baustelle geliefert",
        "Matériau non conforme livré sur le chantier",
    ),
    "ncr_cause_2": (
        "Detail clash identified on site",
        "Detailkollision auf der Baustelle festgestellt",
        "Conflit de détail constaté sur le chantier",
    ),
    "ncr_cause_3": (
        "Inadequate supervision of subcontracted works",
        "Unzureichende Überwachung der Nachunternehmerleistungen",
        "Surveillance insuffisante des travaux sous-traités",
    ),
    "ncr_cause_4": (
        "Damage during handling/storage",
        "Beschädigung bei Handhabung/Lagerung",
        "Dégradation lors de la manutention / du stockage",
    ),
    "ncr_cause_5": (
        "Tolerance exceeded at interface",
        "Toleranz an der Schnittstelle überschritten",
        "Tolérance dépassée à l'interface",
    ),
    "ncr_workmanship": ("workmanship", "Ausführung", "exécution"),
    "ncr_title": (
        "{trade} non-conformance - {item}",
        "{trade} Mangel - {item}",
        "Non-conformité {trade} - {item}",
    ),
    "ncr_description": (
        "{cause} for {item} (section {code}).",
        "{cause} bei {item} (Abschnitt {code}).",
        "{cause} pour {item} (section {code}).",
    ),
    "ncr_corrective": (
        "Rework affected area and re-inspect",
        "Betroffenen Bereich nacharbeiten und erneut prüfen",
        "Reprendre la zone concernée et la recontrôler",
    ),
    "ncr_preventive": (
        "Add to hold-point checklist and brief crew",
        "In die Haltepunktliste aufnehmen und Kolonne unterweisen",
        "Ajouter à la liste des points d'arrêt et briefer l'équipe",
    ),
    # ── correspondence ───────────────────────────────────────────────────
    "corr_commencement": (
        "Notice of commencement to {authority}",
        "Baubeginnanzeige an {authority}",
        "Déclaration d'ouverture de chantier à {authority}",
    ),
    "corr_acknowledgement": (
        "{authority} acknowledgement of commencement",
        "Bestätigung des Baubeginns durch {authority}",
        "Accusé de réception de l'ouverture de chantier par {authority}",
    ),
    "corr_insurance": (
        "Submission of insurance certificates and performance bond",
        "Vorlage der Versicherungsnachweise und der Vertragserfüllungsbürgschaft",
        "Remise des attestations d'assurance et de la caution de bonne exécution",
    ),
    "corr_client_instruction": (
        "Client instruction - scope clarification, {trade}",
        "Anweisung des Auftraggebers - Klärung des Leistungsumfangs, {trade}",
        "Instruction du maître d'ouvrage - précision du périmètre, {trade}",
    ),
    "corr_design_clarification": (
        "Design clarification from the consultant - {trade}",
        "Planungsklärung des Fachplaners - {trade}",
        "Précision de conception du bureau d'études - {trade}",
    ),
    "corr_transmittal": (
        "Drawing transmittal cover - {trade} package",
        "Planversand-Anschreiben - Paket {trade}",
        "Bordereau d'envoi de plans - lot {trade}",
    ),
    "corr_progress_report": (
        "Monthly progress report to the client, month {month}",
        "Monatlicher Fortschrittsbericht an den Auftraggeber, Monat {month}",
        "Rapport d'avancement mensuel au maître d'ouvrage, mois {month}",
    ),
    "corr_valuation": (
        "Interim valuation cover letter ({currency})",
        "Anschreiben zur Abschlagsrechnung ({currency})",
        "Lettre d'accompagnement de la situation de travaux ({currency})",
    ),
    "corr_valuation_plain": (
        "Interim valuation cover letter",
        "Anschreiben zur Abschlagsrechnung",
        "Lettre d'accompagnement de la situation de travaux",
    ),
    "corr_early_warning": (
        "Early-warning notice from {firm} - {trade}",
        "Frühwarnhinweis von {firm} - {trade}",
        "Avis d'alerte précoce de {firm} - {trade}",
    ),
    "corr_inspection_report": (
        "{authority} inspection report",
        "Prüfbericht {authority}",
        "Rapport d'inspection de {authority}",
    ),
    # ── variations ───────────────────────────────────────────────────────
    "variation_scope": (
        "additional works",
        "zusätzliche Leistungen",
        "travaux supplémentaires",
    ),
    "variation_title": (
        "Variation - {trade}: {item}",
        "Nachtrag - {trade}: {item}",
        "Avenant - {trade} : {item}",
    ),
    # ── daily diary ──────────────────────────────────────────────────────
    "diary_weather_clear": (
        "Dry and clear, full working day.",
        "Trocken und klar, voller Arbeitstag.",
        "Temps sec et dégagé, journée de travail complète.",
    ),
    "diary_weather_partly_cloudy": (
        "Bright with broken cloud, full working day.",
        "Heiter mit aufgelockerter Bewölkung, voller Arbeitstag.",
        "Éclaircies et nuages épars, journée de travail complète.",
    ),
    "diary_weather_cloudy": (
        "Cloudy but workable conditions.",
        "Bewölkt, aber gut arbeitsfähig.",
        "Ciel nuageux mais conditions de travail correctes.",
    ),
    "diary_weather_overcast": (
        "Overcast all day, work continued to programme.",
        "Ganztägig bedeckt, Arbeiten planmäßig fortgesetzt.",
        "Ciel couvert toute la journée, travaux poursuivis selon le planning.",
    ),
    "diary_weather_fog": (
        "Morning fog, lifting operations held until visibility improved.",
        "Morgennebel, Hebearbeiten bis zur Sichtverbesserung zurückgestellt.",
        "Brouillard le matin, levages suspendus jusqu'à une meilleure visibilité.",
    ),
    "diary_weather_rain": (
        "Intermittent rain, external works paused in the afternoon.",
        "Zeitweiser Regen, Außenarbeiten am Nachmittag unterbrochen.",
        "Pluie intermittente, travaux extérieurs interrompus l'après-midi.",
    ),
    "diary_activity_0": (
        "set out and survey checks completed",
        "Absteckung und Vermessungskontrollen abgeschlossen",
        "implantation et contrôles topographiques terminés",
    ),
    "diary_activity_1": (
        "main lift / pour completed to programme",
        "Haupthub / Betonage planmäßig abgeschlossen",
        "levage / bétonnage principal réalisé selon le planning",
    ),
    "diary_activity_2": (
        "inspection and sign-off of the previous section",
        "Prüfung und Abnahme des vorherigen Abschnitts",
        "contrôle et réception du tronçon précédent",
    ),
    "diary_activity_3": (
        "material deliveries received and checked in",
        "Materiallieferungen angenommen und geprüft",
        "livraisons de matériaux réceptionnées et contrôlées",
    ),
    "diary_activity_4": (
        "follow-on trade started behind the leading gang",
        "Folgegewerk hinter der vorlaufenden Kolonne gestartet",
        "lot suivant démarré derrière l'équipe de tête",
    ),
    "diary_notes": (
        "{weather} {labour} operatives and {equip} items of plant on site. {trade}: {activity}.",
        "{weather} {labour} Arbeitskräfte und {equip} Geräte auf der Baustelle. {trade}: {activity}.",
        "{weather} {labour} ouvriers et {equip} engins sur le chantier. {trade} : {activity}.",
    ),
    "diary_delay": (
        " Approx. 2 hours lost to weather; recovered against float.",
        " Ca. 2 Stunden witterungsbedingt verloren; über den Puffer aufgeholt.",
        " Environ 2 heures perdues à cause de la météo ; rattrapées sur la marge.",
    ),
    # ── compliance register ──────────────────────────────────────────────
    "compliance_name_0": (
        "Contractor all-risk insurance (CAR)",
        "Bauleistungsversicherung (CAR)",
        "Assurance tous risques chantier (TRC)",
    ),
    "compliance_issuer_0": ("Insurer", "Versicherer", "Assureur"),
    "compliance_name_1": (
        "Public liability insurance",
        "Betriebshaftpflichtversicherung",
        "Assurance responsabilité civile",
    ),
    "compliance_issuer_1": ("Insurer", "Versicherer", "Assureur"),
    "compliance_name_2": ("Performance bond", "Vertragserfüllungsbürgschaft", "Caution de bonne exécution"),
    "compliance_issuer_2": ("Surety", "Bürgschaftsgeber", "Garant"),
    "compliance_name_3": ("Building / construction permit", "Baugenehmigung", "Permis de construire"),
    "compliance_issuer_3": ("Local authority", "Örtliche Behörde", "Collectivité locale"),
    "compliance_name_4": (
        "ISO 9001 quality certification",
        "Qualitätszertifizierung nach ISO 9001",
        "Certification qualité ISO 9001",
    ),
    "compliance_issuer_4": ("Certification body", "Zertifizierungsstelle", "Organisme de certification"),
    "compliance_name_5": (
        "Site environmental permit",
        "Umweltgenehmigung für die Baustelle",
        "Autorisation environnementale du chantier",
    ),
    "compliance_issuer_5": ("Environmental authority", "Umweltbehörde", "Autorité environnementale"),
    "compliance_notes": ("{name} for {proj}.", "{name} für {proj}.", "{name} pour {proj}."),
    # ── procurement, contracts, transmittals ─────────────────────────────
    "po_subject": ("supply for {trade}", "Lieferung für {trade}", "fourniture pour {trade}"),
    "po_line": ("{item} - supply", "{item} - Lieferung", "{item} - fourniture"),
    "contract_main_title": (
        "Main construction contract - {proj}",
        "Bauvertrag Generalunternehmer - {proj}",
        "Marché de travaux principal - {proj}",
    ),
    "contract_sub_subject": (
        "Subcontract - {trade}",
        "Nachunternehmervertrag - {trade}",
        "Contrat de sous-traitance - {trade}",
    ),
    "transmittal_subject": (
        "{trade} drawings and specifications",
        "Zeichnungen und Leistungsbeschreibung {trade}",
        "Plans et descriptifs {trade}",
    ),
    "transmittal_cover": (
        "Issue of {item} information for {proj}.",
        "Herausgabe der Unterlagen zu {item} für {proj}.",
        "Diffusion des informations relatives à {item} pour {proj}.",
    ),
    "transmittal_item_0": ("{trade} general arrangement", "{trade} Übersichtsplan", "{trade} plan d'ensemble"),
    "transmittal_item_1": ("{item} detail", "{item} Detail", "{item} détail"),
    # ── resources ────────────────────────────────────────────────────────
    "resource_pm": ("Project Manager", "Projektleiter", "Chef de projet"),
    "resource_sm": ("Site Manager", "Bauleiter", "Conducteur de travaux"),
    "resource_qs": ("Quantity Surveyor", "Kostenplaner", "Économiste de la construction"),
    # ── requirements ─────────────────────────────────────────────────────
    "requirement_set_name": (
        "{standard} requirements - {proj}",
        "Anforderungen {standard} - {proj}",
        "Exigences {standard} - {proj}",
    ),
    "requirement_standard_default": ("Project", "Projekt", "Projet"),
    "requirement_set_description": (
        "Employer information and technical requirements for {proj}.",
        "Auftraggeber-Informationsanforderungen und technische Anforderungen für {proj}.",
        "Exigences d'information et exigences techniques du maître d'ouvrage pour {proj}.",
    ),
    "requirement_entity": ("Element", "Bauteil", "Élément"),
    "requirement_category": ("general", "allgemein", "général"),
    "requirement_source": ("Section {code}", "Abschnitt {code}", "Section {code}"),
    "requirement_value_spec": ("as specification", "gemäß Leistungsbeschreibung", "selon descriptif"),
    # ── progress ─────────────────────────────────────────────────────────
    "progress_plan_note": ("Planned S-curve", "Geplante S-Kurve", "Courbe en S planifiée"),
    "progress_note": (
        "Cumulative progress at {period}.",
        "Kumulierter Fortschritt zum {period}.",
        "Avancement cumulé à {period}.",
    ),
    # ── risks ────────────────────────────────────────────────────────────
    "risk_title_0": (
        "Design coordination gaps between disciplines",
        "Koordinierungslücken zwischen den Planungsdisziplinen",
        "Défauts de coordination entre les disciplines de conception",
    ),
    "risk_mitigation_0": (
        "Run weekly BIM coordination workshops and resolve clashes before construction.",
        "Wöchentliche BIM-Koordinierungsworkshops durchführen und Kollisionen vor Baubeginn lösen.",
        "Organiser des ateliers hebdomadaires de coordination BIM et résoudre les conflits avant les travaux.",
    ),
    "risk_title_1": (
        "Delayed material deliveries for long-lead items",
        "Verspätete Materiallieferungen bei Bauteilen mit langer Lieferzeit",
        "Retards de livraison des éléments à long délai",
    ),
    "risk_mitigation_1": (
        "Place early procurement orders and track lead times in the procurement log.",
        "Frühzeitig bestellen und Lieferzeiten im Beschaffungsprotokoll verfolgen.",
        "Passer les commandes tôt et suivre les délais dans le registre des achats.",
    ),
    "risk_title_2": (
        "Material price escalation over the build period",
        "Materialpreissteigerungen während der Bauzeit",
        "Hausse des prix des matériaux pendant la durée des travaux",
    ),
    "risk_mitigation_2": (
        "Lock prices with framework agreements and carry an escalation allowance.",
        "Preise über Rahmenverträge sichern und eine Preisgleitreserve vorsehen.",
        "Sécuriser les prix par des accords-cadres et prévoir une provision pour révision.",
    ),
    "risk_title_3": (
        "Working-at-height and lifting operations exposure",
        "Gefährdung durch Arbeiten in der Höhe und Hebevorgänge",
        "Exposition aux travaux en hauteur et aux opérations de levage",
    ),
    "risk_mitigation_3": (
        "Enforce permit-to-work, lift plans and daily toolbox talks.",
        "Arbeitsfreigaben, Hubpläne und tägliche Kurzunterweisungen durchsetzen.",
        "Imposer le permis de travail, les plans de levage et des causeries sécurité quotidiennes.",
    ),
    "risk_title_4": (
        "Limited availability of specialist subcontractors",
        "Begrenzte Verfügbarkeit von Spezial-Nachunternehmern",
        "Disponibilité limitée de sous-traitants spécialisés",
    ),
    "risk_mitigation_4": (
        "Pre-qualify at least three subcontractors per specialist trade.",
        "Pro Spezialgewerk mindestens drei Nachunternehmer präqualifizieren.",
        "Préqualifier au moins trois sous-traitants par corps d'état spécialisé.",
    ),
    "risk_title_5": (
        "Unforeseen ground or existing-condition issues",
        "Unvorhergesehene Baugrund- oder Bestandsprobleme",
        "Aléas de sol ou de l'existant imprévus",
    ),
    "risk_mitigation_5": (
        "Commission additional site investigation before excavation.",
        "Vor dem Aushub zusätzliche Baugrunduntersuchungen beauftragen.",
        "Commander des reconnaissances complémentaires avant les terrassements.",
    ),
    "risk_title_6": (
        "Adverse weather disrupting the critical path",
        "Schlechtwetter gefährdet den kritischen Pfad",
        "Intempéries perturbant le chemin critique",
    ),
    "risk_mitigation_6": (
        "Sequence weather-sensitive works into favourable months and build in float.",
        "Witterungsempfindliche Arbeiten in günstige Monate legen und Puffer einplanen.",
        "Planifier les travaux sensibles aux intempéries en saison favorable et prévoir de la marge.",
    ),
    "risk_description": (
        "{title} affecting {trade} for {proj}.",
        "{title} mit Auswirkung auf {trade} bei {proj}.",
        "{title} avec incidence sur {trade} pour {proj}.",
    ),
}

#: Language -> key -> text, the same shape as the install's own wording table.
GENERATED_TEXT: dict[str, dict[str, str]] = {
    "en": {key: row[0] for key, row in _ROWS.items()},
    "de": {key: row[1] for key, row in _ROWS.items()},
    "fr": {key: row[2] for key, row in _ROWS.items()},
}

#: The authority a start of works is notified to, by language and country code. The German forms carry no
#: article (the register line reads "Baubeginnanzeige an Bauaufsichtsamt"), the French ones do.
AUTHORITY: dict[str, dict[str, str]] = {
    "de": {"DE": "Bauaufsichtsamt", "AT": "Baubehörde", "CH": "Baubewilligungsbehörde"},
    "fr": {"FR": "la mairie", "CH": "l'autorité cantonale des constructions"},
}

#: English sentences carried by hand-written demo rows, by target language.
PHRASES: dict[str, dict[str, str]] = {
    "de": {
        # tasks
        "Commission geotechnical survey for foundation design": "Baugrundgutachten für die Gründungsplanung beauftragen",
        "Report received, no contamination found": "Gutachten liegt vor, keine Schadstoffbelastung festgestellt",
        "Review sheet pile wall structural calculations with engineer": (
            "Statik der Spundwand mit dem Tragwerksplaner prüfen"
        ),
        "Choose between Sanverth ThermFix Classic vs Odenau Granulat": (
            "Auswahl zwischen Sanverth ThermFix Classic und Odenau Granulat"
        ),
        "Sanverth ThermFix Classic selected - better thermal performance": (
            "Sanverth ThermFix Classic gewählt - bessere Wärmedämmleistung"
        ),
        "Prepare KfW subsidy application for energy-efficient building": (
            "KfW-Förderantrag für das energieeffiziente Gebäude vorbereiten"
        ),
        "Coordinate underground parking smoke extraction with fire authority": (
            "Entrauchung der Tiefgarage mit der Brandschutzbehörde abstimmen"
        ),
        "Compare lift offers from Ascentia, Verticore, and Hebwerk Nord": (
            "Aufzugsangebote von Ascentia, Verticore und Hebwerk Nord vergleichen"
        ),
        "Present facade color concept to tenant advisory board": "Fassadenfarbkonzept dem Mieterbeirat vorstellen",
        # meetings
        "Kick-off meeting held on site. All parties confirmed readiness to start.": (
            "Auftaktbesprechung auf der Baustelle abgehalten. Alle Beteiligten bestätigten die Startbereitschaft."
        ),
        "Site logistics plan review": "Prüfung des Baustelleneinrichtungsplans",
        "Approved with minor adjustments": "Mit kleinen Anpassungen freigegeben",
        "Health and safety briefing": "Unterweisung zu Arbeits- und Gesundheitsschutz",
        "All trades briefed": "Alle Gewerke unterwiesen",
        "Foundation programme review": "Prüfung des Gründungsprogramms",
        "On track for April start": "Im Plan für den Start im April",
        "Submit revised site logistics plan": "Überarbeiteten Baustelleneinrichtungsplan einreichen",
        "Arrange crane base survey": "Vermessung des Kranfundaments veranlassen",
        "Earthworks progress - 60% complete": "Stand Erdarbeiten - 60 % fertiggestellt",
        "On programme": "Im Terminplan",
        "Dewatering pump issue": "Störung der Wasserhaltungspumpe",
        "Pump replaced, running OK": "Pumpe ersetzt, läuft einwandfrei",
        "Order replacement dewatering pump as standby": "Ersatzpumpe für die Wasserhaltung als Reserve bestellen",
        "WDVS detail at window reveals": "WDVS-Detail an den Fensterleibungen",
        "Color scheme final selection": "Endgültige Farbauswahl",
        "Thermal bridge calculations review": "Prüfung der Wärmebrückenberechnungen",
        # safety incidents
        "Near miss - unsecured scaffold plank": "Beinaheunfall - ungesicherte Gerüstbohle",
        "Level 2, Grid C-D / 4-5": "Ebene 2, Achse C-D / 4-5",
        (
            "Scaffold plank found unsecured on level 2 platform during morning inspection. Wind gust could have "
            "displaced board onto workers below."
        ): (
            "Bei der morgendlichen Kontrolle wurde auf der Plattform der Ebene 2 eine ungesicherte Gerüstbohle "
            "festgestellt. Eine Windböe hätte das Brett auf darunter arbeitende Personen werfen können."
        ),
        "Scaffolders did not complete toe-board installation before leaving for break": (
            "Die Gerüstbauer haben die Bordbretter vor der Pause nicht fertig montiert"
        ),
        "Minor hand injury - rebar handling": "Leichte Handverletzung - Umgang mit Bewehrung",
        "Foundation zone, Grid A-B / 1-3": "Gründungsbereich, Achse A-B / 1-3",
        "Worker cut left hand while handling rebar ties. Cut treated on site with first aid.": (
            "Ein Arbeiter schnitt sich beim Umgang mit Bewehrungsbindedraht in die linke Hand. Die Wunde wurde "
            "vor Ort mit Erster Hilfe versorgt."
        ),
        "Worker removed gloves to tie wire, hand slipped on rebar end": (
            "Der Arbeiter zog zum Binden die Handschuhe aus, die Hand rutschte am Bewehrungsende ab"
        ),
        "Rebar fitter": "Eisenflechter",
        "Retrain scaffold team on completion requirements": (
            "Gerüstbauteam erneut zu den Fertigstellungsanforderungen unterweisen"
        ),
        "Implement scaffold handover checklist": "Übergabe-Checkliste für Gerüste einführen",
        "Toolbox talk on mandatory glove use": "Kurzunterweisung zur Handschuhpflicht",
        # safety observations
        (
            "Scaffold missing handrail on south elevation, level 3. Top lift not yet completed but workers "
            "accessing area."
        ): (
            "Am Gerüst der Südseite, Ebene 3, fehlt das Geländer. Die oberste Lage ist noch nicht fertig, der "
            "Bereich wird aber bereits betreten."
        ),
        "South elevation, Level 3": "Südansicht, Ebene 3",
        "Area cordoned off until handrail installed": "Bereich abgesperrt, bis das Geländer montiert ist",
        "Scaffolders to complete handrails before platform use": (
            "Gerüstbauer montieren die Geländer vor der Nutzung der Plattform"
        ),
        "Two workers observed not wearing safety glasses during concrete cutting.": (
            "Zwei Arbeiter trugen beim Betontrennen keine Schutzbrille."
        ),
        "Ground floor slab, Grid E/5": "Bodenplatte Erdgeschoss, Achse E/5",
        "Workers stopped and issued PPE": "Arbeiten gestoppt, PSA ausgegeben",
        "Toolbox talk on mandatory eye protection for cutting works": (
            "Kurzunterweisung zur Augenschutzpflicht bei Trennarbeiten"
        ),
        "Debris and loose materials blocking emergency exit route at level 1.": (
            "Schutt und lose Materialien versperren den Fluchtweg auf Ebene 1."
        ),
        "Stairwell 2, Level 1": "Treppenhaus 2, Ebene 1",
        "Area cleared immediately": "Bereich sofort geräumt",
        "Weekly housekeeping audit added to site inspection schedule": (
            "Wöchentliche Ordnungsprüfung in den Begehungsplan aufgenommen"
        ),
        # punch list
        "Hairline crack (0.3mm) in basement slab at grid C3. Needs epoxy injection.": (
            "Haarriss (0,3 mm) in der Bodenplatte des Untergeschosses bei Achse C3. Epoxidharzinjektion erforderlich."
        ),
        "EIFS adhesive blistering on south facade Level 2, approx 2m2 area.": (
            "Blasenbildung im WDVS-Kleber an der Südfassade, Ebene 2, ca. 2 m² Fläche."
        ),
        "3 missing fire collars at service penetrations in riser R2 (per INS-003).": (
            "3 fehlende Brandschutzmanschetten an Leitungsdurchführungen im Steigschacht R2 (gemäß INS-003)."
        ),
        "Fire stopping": "Brandabschottung",
        "Concrete": "Beton",
        "Plumbing": "Sanitär",
        "WDVS/Facade": "WDVS/Fassade",
        "Fire collars ordered, installation scheduled for next week": (
            "Brandschutzmanschetten bestellt, Einbau für nächste Woche geplant"
        ),
        "Minor leak at manifold connection in apartment 3.04.": (
            "Geringe Undichtigkeit am Verteileranschluss in Wohnung 3.04."
        ),
        "Fitting retightened, pressure test passed": "Verschraubung nachgezogen, Druckprüfung bestanden",
        # site reports
        (
            "Spundwandverbau Larssen 603 installation completed south wall. Dewatering pumps operational. "
            "Excavation proceeding grid A-C."
        ): (
            "Spundwandverbau Larssen 603 an der Südwand abgeschlossen. Wasserhaltungspumpen in Betrieb. Aushub "
            "schreitet in den Achsen A-C voran."
        ),
        "Piling crew": "Verbaukolonne",
        "Excavation crew": "Aushubkolonne",
        "General labor": "Hilfskräfte",
        "Korvex PB 36 piling rig": "Korvex PB 36 Rammgerät",
        "Tramont T-330 excavator": "Tramont T-330 Bagger",
        "Wellpoint dewatering system": "Brunnen-Wasserhaltungsanlage",
        (
            "Excavation paused due to heavy rain. Dewatering pumps running at full capacity. Formwork preparation "
            "in covered area."
        ): (
            "Aushub wegen Starkregen unterbrochen. Wasserhaltungspumpen laufen mit voller Leistung. "
            "Schalungsvorbereitung im überdachten Bereich."
        ),
        "Heavy rain - excavation paused for 4 hours": "Starkregen - Aushub 4 Stunden unterbrochen",
        # submittals, correspondence, contacts
        "WDVS Sanverth ThermFix Classic - product data": "WDVS Sanverth ThermFix Classic - Produktdatenblätter",
        "Official notification of construction start to building authority": (
            "Offizielle Anzeige des Baubeginns an die Bauaufsicht"
        ),
        "Fire authority comments on smoke extract and pressurisation": (
            "Stellungnahme der Feuerwehr zu Rauchabzug und Druckbelüftung"
        ),
        "Main client contact": "Hauptansprechpartner Auftraggeber",
        "Structural works subcontractor": "Nachunternehmer Rohbau",
        "WDVS facade contractor": "WDVS-Fassadenbauer",
        "Lead architect": "Leitender Architekt",
        "Structural engineer": "Tragwerksplaner",
        "MEP subcontractor": "Nachunternehmer TGA",
    },
    "fr": {
        # tasks
        "Commission pre-demolition asbestos survey for existing structures": (
            "Commander le diagnostic amiante avant démolition des structures existantes"
        ),
        "No asbestos detected - demolition cleared": "Aucune présence d'amiante - démolition autorisée",
        "Final decision on CLT timber vs reinforced concrete for superstructure": (
            "Décision finale entre bois CLT et béton armé pour la superstructure"
        ),
        "CLT hybrid selected - meets RE 2020 carbon targets": (
            "Solution hybride CLT retenue - respecte les objectifs carbone de la RE 2020"
        ),
        "Meeting with Mairie to discuss construction phase site logistics": (
            "Réunion avec la mairie sur la logistique de chantier pendant la phase travaux"
        ),
        "Prepare tender documents for commercial kitchen equipment": (
            "Préparer le dossier de consultation pour les équipements de cuisine collective"
        ),
        "Acoustic study for gymnasium - ensure NRA compliance": (
            "Étude acoustique du gymnase - garantir la conformité à la NRA"
        ),
        "Size rooftop PV array for 120 kWc target": (
            "Dimensionner le champ photovoltaïque en toiture pour un objectif de 120 kWc"
        ),
        "320 panels on south-facing roof - 125 kWc achieved": "320 panneaux en toiture orientée sud - 125 kWc atteints",
        # meetings
        "Site establishment nearly complete. Demolition commences next week.": (
            "Installation de chantier presque terminée. La démolition commence la semaine prochaine."
        ),
        "Installation chantier - 90% complete": "Installation de chantier - 90 % réalisée",
        "Hoarding installed": "Palissades posées",
        "Demolition programme": "Programme de démolition",
        "Start Monday": "Démarrage lundi",
        "Riverains - noise mitigation plan": "Riverains - plan de réduction du bruit",
        "Approved by mairie": "Validé par la mairie",
        "Submit noise monitoring results weekly": "Transmettre chaque semaine les résultats de mesure du bruit",
        "Install temporary pedestrian walkway": "Installer un cheminement piéton provisoire",
        "CLT panel shop drawing review": "Revue des plans d'atelier des panneaux CLT",
        "Connection details validation": "Validation des détails d'assemblage",
        "Fire protection treatment": "Traitement de protection incendie",
        # safety incidents
        ("CLT panel slipped from storage rack due to improper bracing. No injuries - area was cordoned off."): (
            "Un panneau CLT a glissé du rack de stockage par défaut de contreventement. Aucun blessé - la zone a "
            "été balisée."
        ),
        "Storage rack not rated for CLT panel weight. Wind loading not considered.": (
            "Rack de stockage non dimensionné pour le poids des panneaux CLT. Action du vent non prise en compte."
        ),
        "Replace temporary racks with rated storage system": (
            "Remplacer les racks provisoires par un système de stockage dimensionné"
        ),
        "Review wind loading on all temporary structures": (
            "Vérifier l'action du vent sur toutes les structures provisoires"
        ),
        # safety observations
        "Tranchee ouverte sans protection - open trench without barrier near school entrance area.": (
            "Tranchée ouverte sans protection près de l'entrée de l'école."
        ),
        "Barriers and warning signs installed": "Barrières et panneaux de signalisation installés",
        "Daily perimeter check for public safety hazards": (
            "Contrôle quotidien du périmètre pour prévenir les risques pour le public"
        ),
        (
            "Demolition noise exceeding 85 dB at property boundary at 07:30. Mairie restriction is 08:00 start "
            "for noisy works."
        ): (
            "Bruit de démolition supérieur à 85 dB en limite de propriété à 7 h 30. La mairie impose un démarrage "
            "à 8 h pour les travaux bruyants."
        ),
        "Works stopped until 08:00, noise barrier repositioned": (
            "Travaux arrêtés jusqu'à 8 h, écran acoustique repositionné"
        ),
        "Site manager to confirm noise levels before 08:00 start": (
            "Le conducteur de travaux vérifie les niveaux de bruit avant le démarrage de 8 h"
        ),
        "Stockage CLT non bache - CLT panels stored without weather protection.": (
            "Stockage CLT non bâché - panneaux CLT stockés sans protection contre les intempéries."
        ),
        "Panels covered with tarpaulin": "Panneaux recouverts d'une bâche",
        "All CLT deliveries to be stored in covered area only": (
            "Toutes les livraisons de CLT doivent être stockées en zone couverte"
        ),
        # punch list
        "CLT panel joint visible and not flush in classroom 1.02. Needs filling and sanding.": (
            "Joint de panneau CLT visible et non affleurant dans la salle de classe 1.02. À reboucher et poncer."
        ),
        "Gymnasium fire door closer not achieving full closure.": (
            "Le ferme-porte de la porte coupe-feu du gymnase ne ferme pas complètement."
        ),
        "Paint peeling in entrance hall near external door - moisture ingress suspected.": (
            "Peinture qui s'écaille dans le hall d'entrée près de la porte extérieure - infiltration d'humidité "
            "suspectée."
        ),
        "CLT/Timber": "CLT/Bois",
        "Doors": "Portes",
        "Painting": "Peinture",
        # site reports
        "Demolition of existing structure 80% complete. Sorting of demolition waste for recycling ongoing.": (
            "Démolition de la structure existante réalisée à 80 %. Tri des déchets de démolition pour recyclage "
            "en cours."
        ),
        "Demolition crew": "Équipe de démolition",
        "Waste sorting": "Tri des déchets",
        "Korvex D 940 demolition excavator": "Pelle de démolition Korvex D 940",
        "Concrete crusher": "Concasseur à béton",
        "Dust suppression system": "Système d'abattage des poussières",
        # correspondence, invoices, contacts
        "Official construction start declaration to mairie": (
            "Déclaration officielle d'ouverture de chantier à la mairie"
        ),
        "CLT panels - 40% advance on fabrication": "Panneaux CLT - acompte de 40 % sur la fabrication",
        "Architect mandate": "Mandat d'architecte",
        "Gros œuvre contractor": "Entreprise de gros œuvre",
        "MEP engineer": "Bureau d'études fluides",
        "CLT timber structure specialist": "Spécialiste structure bois CLT",
    },
}


def language_of(locale: str | None) -> str:
    """The table language for a project locale: ``de`` or ``fr``, else the English default."""
    lang = (locale or "en").lower().replace("_", "-")[:2]
    return lang if lang in LOCALISED_LANGUAGES else "en"


def authority_text(locale: str | None, country_code: str) -> str | None:
    """The notified authority in the project's language, or None when the table has no entry for the country."""
    return AUTHORITY.get(language_of(locale), {}).get(country_code)


def generated_text(locale: str | None, key: str, **values: object) -> str:
    """The wording ``key`` in the project's language (English by default), with ``values`` filled in."""
    table = GENERATED_TEXT[language_of(locale)]
    return table.get(key, GENERATED_TEXT["en"][key]).format(**values)


def localise(locale: str | None, value: Any) -> Any:
    """Return ``value`` with every English sentence of the phrase table replaced by the project's language.

    Walks dicts, lists and tuples of any depth and replaces a string only when it is an exact key of the phrase
    table, so codes, numbers, names and text that is already in the project's language pass through unchanged.
    """
    table = PHRASES.get(language_of(locale))
    if not table:
        return value
    return _walk(table, value)


def _walk(table: dict[str, str], value: Any) -> Any:
    if isinstance(value, str):
        return table.get(value, value)
    if isinstance(value, dict):
        return {key: _walk(table, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_walk(table, item) for item in value]
    if isinstance(value, tuple):
        return tuple(_walk(table, item) for item in value)
    return value
