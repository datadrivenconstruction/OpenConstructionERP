# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""German and French wording of the mobilisation checklist the demo seeds, keyed by the English sentence."""

from __future__ import annotations

from app.core.demo_locale_text import language_of

PHRASES: dict[str, dict[str, str]] = {
    "de": {
        "Mobilisation plan for the works. Readiness is measured against the target start date; the commencement gates must all be closed before anyone breaks ground.": (
            "Einrichtungsplan für die Baumaßnahme. Die Bereitschaft wird am Soll-Starttermin gemessen; alle "
            "Startfreigaben müssen geschlossen sein, bevor jemand mit den Erdarbeiten beginnt."
        ),
        # responsible parties
        "Project manager": "Projektleiter",
        "HSE manager": "Sicherheitsbeauftragter (SiGeKo)",
        "Site manager": "Bauleiter",
        "Site supervisor": "Polier",
        "MEP contractor": "Auftragnehmer Gebäudetechnik",
        "Temporary works coordinator": "Koordinator Hilfskonstruktionen",
        "Environmental manager": "Umweltbeauftragter",
        "Commercial manager": "Kaufmännischer Leiter",
        "Logistics manager": "Logistikleiter",
        # checklist
        "Building permit issued and displayed on site": "Baugenehmigung erteilt und auf der Baustelle ausgehängt",
        "Permit received from the authority, copy posted at the site entrance.": (
            "Genehmigung der Behörde liegt vor, Kopie am Baustelleneingang ausgehängt."
        ),
        "Notification of the works submitted to the safety regulator": (
            "Baubeginnanzeige bei der Arbeitsschutzbehörde eingereicht"
        ),
        "Statutory notification lodged before mobilisation, acknowledgement filed.": (
            "Gesetzliche Anzeige vor der Baustelleneinrichtung eingereicht, Eingangsbestätigung abgelegt."
        ),
        "Highway and footway licences obtained": "Sondernutzungserlaubnisse für Straße und Gehweg eingeholt",
        "Licences for the crossing, scaffold over the footway and any lane closure.": (
            "Erlaubnisse für die Zufahrt, das Gerüst über dem Gehweg und jede Fahrbahnsperrung."
        ),
        "Utility diversion consents received": "Zustimmungen zur Verlegung von Leitungen liegen vor",
        "Consents from each utility whose apparatus is affected by the enabling works.": (
            "Zustimmung jedes Versorgers, dessen Anlagen von den vorbereitenden Arbeiten betroffen sind."
        ),
        "Construction phase health and safety plan issued": "SiGe-Plan für die Bauphase herausgegeben",
        "Plan issued to the client and the trades, revision controlled.": (
            "Plan an den Auftraggeber und die Gewerke verteilt, Revisionsstand geführt."
        ),
        "Site access route agreed with the highway authority": "Baustellenzufahrt mit der Straßenbehörde abgestimmt",
        "Approved route for construction traffic, including approach and egress.": (
            "Genehmigte Route für den Baustellenverkehr einschließlich An- und Abfahrt."
        ),
        "Gate positions and delivery turning circle set out": "Torpositionen und Wendekreis für Anlieferungen abgesteckt",
        "Entrance and exit gates positioned, swept path checked against the largest vehicle.": (
            "Ein- und Ausfahrtstore festgelegt, Schleppkurve für das größte Fahrzeug geprüft."
        ),
        "Wheel wash and road sweeping arrangements in place": "Reifenwäsche und Straßenreinigung eingerichtet",
        "Wheel wash sited at the exit, sweeper booked for the haul route.": (
            "Reifenwaschanlage an der Ausfahrt, Kehrmaschine für die Transportroute bestellt."
        ),
        "Perimeter hoarding erected and signed": "Bauzaun errichtet und beschildert",
        "Continuous boundary to the full site, warning and information signage fixed.": (
            "Geschlossene Umzäunung der gesamten Baustelle, Warn- und Hinweisschilder angebracht."
        ),
        "CCTV and out-of-hours monitoring commissioned": "Videoüberwachung und Überwachung außerhalb der Arbeitszeit in Betrieb",
        "Cameras covering the gates and the compound, monitoring contract live.": (
            "Kameras erfassen Tore und Lagerplatz, Überwachungsvertrag aktiv."
        ),
        "Access control and visitor booking in place": "Zutrittskontrolle und Besucheranmeldung eingerichtet",
        "Turnstile or signing-in point operating, visitor pre-booking published.": (
            "Drehkreuz oder Anmeldestelle in Betrieb, Voranmeldung für Besucher veröffentlicht."
        ),
        "Temporary power supply energised": "Baustrom zugeschaltet",
        "Builder's supply connected, distribution boards installed and tested.": (
            "Baustromanschluss hergestellt, Verteiler installiert und geprüft."
        ),
        "Temporary water supply connected and tested": "Bauwasser angeschlossen und geprüft",
        "Standpipe and site main in service, sample taken for potability.": (
            "Standrohr und Baustellenleitung in Betrieb, Probe auf Trinkwasserqualität entnommen."
        ),
        "Temporary lighting to access routes and stairs": "Bauleuchten auf Zugangswegen und Treppen",
        "Task and route lighting installed, emergency lighting to the escape routes.": (
            "Arbeitsplatz- und Wegebeleuchtung installiert, Notbeleuchtung der Fluchtwege."
        ),
        "Site data and telephony live": "Baustellen-Datennetz und Telefonie in Betrieb",
        "Connectivity to the offices and the gatehouse, coverage checked on the deck.": (
            "Anbindung von Büros und Pförtner, Abdeckung auf der Geschossdecke geprüft."
        ),
        "Welfare units in service before any work starts": "Sozialeinrichtungen vor Arbeitsbeginn in Betrieb",
        "Toilets, washing, drying room and canteen connected and stocked.": (
            "Toiletten, Waschräume, Trockenraum und Kantine angeschlossen und ausgestattet."
        ),
        "Site offices sited and connected": "Baubüros aufgestellt und angeschlossen",
        "Offices and meeting room positioned clear of the crane radius.": (
            "Büros und Besprechungsraum außerhalb des Kranschwenkbereichs aufgestellt."
        ),
        "First aid room equipped and first aiders on the register": (
            "Erste-Hilfe-Raum ausgestattet und Ersthelfer namentlich erfasst"
        ),
        "Equipped room, named first aiders per shift, emergency numbers posted.": (
            "Ausgestatteter Raum, namentlich benannte Ersthelfer je Schicht, Notrufnummern ausgehängt."
        ),
        "Temporary works register opened and coordinator appointed": (
            "Register der Hilfskonstruktionen eröffnet und Koordinator bestellt"
        ),
        "Register live, coordinator named in writing, design brief issued.": (
            "Register geführt, Koordinator schriftlich benannt, Planungsvorgabe ausgegeben."
        ),
        "Crane base design certificate issued": "Bescheinigung der Kranfundament-Planung liegt vor",
        "Design check certificate for the base and its bearing pressure received.": (
            "Prüfbescheinigung für das Fundament und die Bodenpressung liegt vor."
        ),
        "Piling mat design and validation certificate received": (
            "Planung der Bohrplattform und Validierungsbescheinigung liegen vor"
        ),
        "Working platform designed to the rig loads, validation certificate filed.": (
            "Arbeitsplattform für die Gerätelasten bemessen, Validierungsbescheinigung abgelegt."
        ),
        "Excavation support scheme approved": "Baugrubenverbau freigegeben",
        "Support to the bulk dig checked and approved before the first excavation.": (
            "Verbau für den Hauptaushub vor dem ersten Aushub geprüft und freigegeben."
        ),
        "Ecology survey completed and protected species signed off": (
            "Artenschutzprüfung abgeschlossen und geschützte Arten abgenommen"
        ),
        "Survey carried out in season, mitigation agreed before any clearance.": (
            "Kartierung in der Vegetationsperiode durchgeführt, Vermeidungsmaßnahmen vor jeder Rodung abgestimmt."
        ),
        "Surface water discharge consent and silt management in place": (
            "Einleiterlaubnis für Oberflächenwasser und Schlammmanagement vorhanden"
        ),
        "Consent held, settlement tanks sized and sited, discharge point agreed.": (
            "Erlaubnis liegt vor, Absetzbecken bemessen und aufgestellt, Einleitstelle abgestimmt."
        ),
        "Dust and noise monitoring stations installed": "Messstellen für Staub und Lärm installiert",
        "Boundary monitors installed with trigger levels agreed with the authority.": (
            "Grenzmessgeräte installiert, Auslösewerte mit der Behörde abgestimmt."
        ),
        "Waste segregation compound set out": "Abfalltrennplatz eingerichtet",
        "Skips and segregation bays positioned, carrier and consignee registered.": (
            "Container und Trennboxen aufgestellt, Transporteur und Entsorger registriert."
        ),
        "Crane oversail agreements signed with the adjoining owners": (
            "Überschwenkvereinbarungen mit den Nachbareigentümern unterzeichnet"
        ),
        "Written consent for the jib to oversail each affected boundary.": (
            "Schriftliche Zustimmung zum Überschwenken jeder betroffenen Grundstücksgrenze durch den Ausleger."
        ),
        "Laydown areas and material storage allocated": "Lager- und Materialflächen zugewiesen",
        "Storage zones allocated per trade, loading bays kept clear of the access route.": (
            "Lagerzonen je Gewerk zugewiesen, Ladebereiche von der Zufahrt freigehalten."
        ),
        "Delivery management system published to the supply chain": (
            "Anlieferungssteuerung an die Lieferkette veröffentlicht"
        ),
        "Booking slots open, delivery rules issued to every subcontractor.": (
            "Zeitfenster buchbar, Anlieferregeln an jeden Nachunternehmer verteilt."
        ),
        "Traffic management plan issued to hauliers": "Verkehrsführungsplan an die Spediteure verteilt",
        "Routes, holding areas and banksman positions issued and acknowledged.": (
            "Routen, Wartebereiche und Einweiserstandorte verteilt und bestätigt."
        ),
        "Site induction pack written and approved": "Unterweisungsunterlagen für die Baustelle erstellt und freigegeben",
        "Induction covering the hazards, the rules and the emergency arrangements.": (
            "Unterweisung zu Gefährdungen, Regeln und Notfallmaßnahmen."
        ),
        "Emergency and evacuation procedure briefed": "Notfall- und Räumungsverfahren unterwiesen",
        "Muster points set, procedure briefed and the first drill scheduled.": (
            "Sammelplätze festgelegt, Verfahren unterwiesen und erste Übung angesetzt."
        ),
        "Competence and training records collected for the first trades": (
            "Befähigungs- und Schulungsnachweise der ersten Gewerke gesammelt"
        ),
        "Cards and tickets checked for every operative mobilising in the first weeks.": (
            "Ausweise und Qualifikationsnachweise aller in den ersten Wochen eingesetzten Beschäftigten geprüft."
        ),
        "Toolbox talk schedule published": "Terminplan der Unterweisungen veröffentlicht",
        "Rolling schedule of talks agreed with each trade for the opening month.": (
            "Fortlaufender Unterweisungsplan für den ersten Monat mit jedem Gewerk abgestimmt."
        ),
        "Pre-condition survey of the adjoining properties recorded": (
            "Beweissicherung an den angrenzenden Gebäuden dokumentiert"
        ),
        "Photographic and written record agreed with each neighbour before work starts.": (
            "Foto- und Schriftdokumentation vor Arbeitsbeginn mit jedem Nachbarn abgestimmt."
        ),
        "Neighbour notification letters issued": "Anliegerschreiben versandt",
        "Letters issued with the working hours, the contact number and the start date.": (
            "Schreiben mit Arbeitszeiten, Ansprechpartner und Starttermin versandt."
        ),
        # blocked and not-applicable reasons
        "Waiting on the authority; chased twice, no date given yet.": (
            "Wartet auf die Behörde; zweimal nachgefragt, noch kein Termin genannt."
        ),
        "Design information outstanding from the consultant.": "Planungsunterlagen des Fachplaners stehen noch aus.",
        "Adjoining owner has not returned the signed agreement.": (
            "Der Nachbareigentümer hat die unterzeichnete Vereinbarung nicht zurückgesandt."
        ),
        "Utility provider cannot attend before the target start date.": (
            "Der Versorger kann vor dem Soll-Starttermin nicht kommen."
        ),
        "Survey could not be completed in season; revised window agreed.": (
            "Kartierung nicht in der Vegetationsperiode abschließbar; neues Zeitfenster vereinbart."
        ),
        "Not applicable: the site is served by the existing permanent supply.": (
            "Entfällt: Die Baustelle wird über den bestehenden dauerhaften Anschluss versorgt."
        ),
        "Not applicable: no adjoining boundary is oversailed on this site.": (
            "Entfällt: Auf dieser Baustelle wird keine Grundstücksgrenze überschwenkt."
        ),
        "Not applicable: works are wholly within the existing curtilage.": (
            "Entfällt: Die Arbeiten finden vollständig auf dem vorhandenen Grundstück statt."
        ),
        "Not applicable: no excavation below the founding level on this package.": (
            "Entfällt: In diesem Los wird nicht unter die Gründungssohle ausgehoben."
        ),
    },
    "fr": {
        "Mobilisation plan for the works. Readiness is measured against the target start date; the commencement gates must all be closed before anyone breaks ground.": (
            "Plan d'installation de chantier. La préparation est mesurée par rapport à la date de démarrage "
            "visée ; tous les points d'arrêt de démarrage doivent être levés avant le premier coup de pelle."
        ),
        "Project manager": "Chef de projet",
        "HSE manager": "Responsable HSE",
        "Site manager": "Conducteur de travaux",
        "Site supervisor": "Chef de chantier",
        "MEP contractor": "Entreprise de lots techniques",
        "Temporary works coordinator": "Coordinateur des ouvrages provisoires",
        "Environmental manager": "Responsable environnement",
        "Commercial manager": "Responsable commercial",
        "Logistics manager": "Responsable logistique",
        "Building permit issued and displayed on site": "Permis de construire délivré et affiché sur le chantier",
        "Permit received from the authority, copy posted at the site entrance.": (
            "Arrêté reçu de l'autorité, copie affichée à l'entrée du chantier."
        ),
        "Notification of the works submitted to the safety regulator": (
            "Déclaration d'ouverture de chantier transmise à l'autorité de sécurité"
        ),
        "Statutory notification lodged before mobilisation, acknowledgement filed.": (
            "Déclaration réglementaire déposée avant l'installation, accusé de réception classé."
        ),
        "Highway and footway licences obtained": "Autorisations de voirie et de trottoir obtenues",
        "Licences for the crossing, scaffold over the footway and any lane closure.": (
            "Autorisations pour l'accès, l'échafaudage au-dessus du trottoir et toute fermeture de voie."
        ),
        "Utility diversion consents received": "Accords de dévoiement des réseaux reçus",
        "Consents from each utility whose apparatus is affected by the enabling works.": (
            "Accord de chaque concessionnaire dont les ouvrages sont touchés par les travaux préparatoires."
        ),
        "Construction phase health and safety plan issued": "PPSPS de la phase travaux diffusé",
        "Plan issued to the client and the trades, revision controlled.": (
            "Plan diffusé au maître d'ouvrage et aux corps d'état, indices de révision suivis."
        ),
        "Site access route agreed with the highway authority": "Itinéraire d'accès au chantier validé par le gestionnaire de voirie",
        "Approved route for construction traffic, including approach and egress.": (
            "Itinéraire approuvé pour la circulation de chantier, entrées et sorties comprises."
        ),
        "Gate positions and delivery turning circle set out": "Portails et giratoire de livraison implantés",
        "Entrance and exit gates positioned, swept path checked against the largest vehicle.": (
            "Portails d'entrée et de sortie positionnés, giration vérifiée pour le plus grand véhicule."
        ),
        "Wheel wash and road sweeping arrangements in place": "Lave-roues et nettoyage de la voirie en place",
        "Wheel wash sited at the exit, sweeper booked for the haul route.": (
            "Lave-roues installé à la sortie, balayeuse réservée pour l'itinéraire de camions."
        ),
        "Perimeter hoarding erected and signed": "Clôture de chantier montée et signalée",
        "Continuous boundary to the full site, warning and information signage fixed.": (
            "Clôture continue sur tout le chantier, panneaux d'avertissement et d'information posés."
        ),
        "CCTV and out-of-hours monitoring commissioned": "Vidéosurveillance et télésurveillance hors horaires mises en service",
        "Cameras covering the gates and the compound, monitoring contract live.": (
            "Caméras sur les portails et la base vie, contrat de télésurveillance actif."
        ),
        "Access control and visitor booking in place": "Contrôle d'accès et enregistrement des visiteurs en place",
        "Turnstile or signing-in point operating, visitor pre-booking published.": (
            "Tourniquet ou point d'accueil en service, pré-enregistrement des visiteurs publié."
        ),
        "Temporary power supply energised": "Alimentation électrique provisoire mise sous tension",
        "Builder's supply connected, distribution boards installed and tested.": (
            "Branchement de chantier raccordé, tableaux de distribution installés et testés."
        ),
        "Temporary water supply connected and tested": "Alimentation en eau provisoire raccordée et testée",
        "Standpipe and site main in service, sample taken for potability.": (
            "Borne et réseau de chantier en service, prélèvement effectué pour la potabilité."
        ),
        "Temporary lighting to access routes and stairs": "Éclairage provisoire des cheminements et escaliers",
        "Task and route lighting installed, emergency lighting to the escape routes.": (
            "Éclairage des postes et des cheminements installé, éclairage de sécurité des évacuations."
        ),
        "Site data and telephony live": "Réseau de données et téléphonie de chantier en service",
        "Connectivity to the offices and the gatehouse, coverage checked on the deck.": (
            "Liaison avec les bureaux et la loge, couverture vérifiée sur le plancher."
        ),
        "Welfare units in service before any work starts": "Locaux sociaux en service avant tout démarrage",
        "Toilets, washing, drying room and canteen connected and stocked.": (
            "Sanitaires, lavabos, séchoir et réfectoire raccordés et approvisionnés."
        ),
        "Site offices sited and connected": "Bungalows de chantier installés et raccordés",
        "Offices and meeting room positioned clear of the crane radius.": (
            "Bureaux et salle de réunion implantés hors du rayon d'action de la grue."
        ),
        "First aid room equipped and first aiders on the register": (
            "Local de secours équipé et sauveteurs secouristes du travail inscrits au registre"
        ),
        "Equipped room, named first aiders per shift, emergency numbers posted.": (
            "Local équipé, secouristes nommés par équipe, numéros d'urgence affichés."
        ),
        "Temporary works register opened and coordinator appointed": (
            "Registre des ouvrages provisoires ouvert et coordinateur désigné"
        ),
        "Register live, coordinator named in writing, design brief issued.": (
            "Registre tenu, coordinateur désigné par écrit, cahier des charges de conception diffusé."
        ),
        "Crane base design certificate issued": "Attestation de conception du massif de grue délivrée",
        "Design check certificate for the base and its bearing pressure received.": (
            "Attestation de vérification du massif et de la contrainte sur le sol reçue."
        ),
        "Piling mat design and validation certificate received": (
            "Note de calcul et attestation de validation de la plateforme de forage reçues"
        ),
        "Working platform designed to the rig loads, validation certificate filed.": (
            "Plateforme de travail dimensionnée pour les charges de la machine, attestation de validation classée."
        ),
        "Excavation support scheme approved": "Dispositif de soutènement des fouilles approuvé",
        "Support to the bulk dig checked and approved before the first excavation.": (
            "Soutènement du terrassement général vérifié et approuvé avant la première fouille."
        ),
        "Ecology survey completed and protected species signed off": (
            "Diagnostic écologique réalisé et espèces protégées validées"
        ),
        "Survey carried out in season, mitigation agreed before any clearance.": (
            "Inventaire réalisé en saison, mesures d'évitement convenues avant tout défrichement."
        ),
        "Surface water discharge consent and silt management in place": (
            "Autorisation de rejet des eaux pluviales et gestion des fines en place"
        ),
        "Consent held, settlement tanks sized and sited, discharge point agreed.": (
            "Autorisation obtenue, bassins de décantation dimensionnés et implantés, exutoire convenu."
        ),
        "Dust and noise monitoring stations installed": "Stations de mesure des poussières et du bruit installées",
        "Boundary monitors installed with trigger levels agreed with the authority.": (
            "Capteurs en limite de site installés, seuils d'alerte convenus avec l'autorité."
        ),
        "Waste segregation compound set out": "Aire de tri des déchets aménagée",
        "Skips and segregation bays positioned, carrier and consignee registered.": (
            "Bennes et bacs de tri positionnés, transporteur et destinataire enregistrés."
        ),
        "Crane oversail agreements signed with the adjoining owners": (
            "Conventions de survol de grue signées avec les propriétaires voisins"
        ),
        "Written consent for the jib to oversail each affected boundary.": (
            "Accord écrit pour le survol de chaque limite concernée par la flèche."
        ),
        "Laydown areas and material storage allocated": "Aires de stockage et de livraison attribuées",
        "Storage zones allocated per trade, loading bays kept clear of the access route.": (
            "Zones de stockage attribuées par corps d'état, quais de chargement dégagés de l'accès."
        ),
        "Delivery management system published to the supply chain": (
            "Système de gestion des livraisons communiqué aux fournisseurs"
        ),
        "Booking slots open, delivery rules issued to every subcontractor.": (
            "Créneaux ouverts à la réservation, règles de livraison diffusées à chaque sous-traitant."
        ),
        "Traffic management plan issued to hauliers": "Plan de circulation diffusé aux transporteurs",
        "Routes, holding areas and banksman positions issued and acknowledged.": (
            "Itinéraires, zones d'attente et postes de signaleurs diffusés et acquittés."
        ),
        "Site induction pack written and approved": "Livret d'accueil du chantier rédigé et approuvé",
        "Induction covering the hazards, the rules and the emergency arrangements.": (
            "Accueil couvrant les dangers, les règles et les dispositions d'urgence."
        ),
        "Emergency and evacuation procedure briefed": "Procédure d'urgence et d'évacuation présentée",
        "Muster points set, procedure briefed and the first drill scheduled.": (
            "Points de rassemblement fixés, procédure présentée et premier exercice programmé."
        ),
        "Competence and training records collected for the first trades": (
            "Attestations de compétence et de formation recueillies pour les premiers corps d'état"
        ),
        "Cards and tickets checked for every operative mobilising in the first weeks.": (
            "Cartes et habilitations vérifiées pour chaque compagnon intervenant les premières semaines."
        ),
        "Toolbox talk schedule published": "Planning des causeries sécurité publié",
        "Rolling schedule of talks agreed with each trade for the opening month.": (
            "Planning glissant des causeries convenu avec chaque corps d'état pour le premier mois."
        ),
        "Pre-condition survey of the adjoining properties recorded": "Constat d'huissier ou d'état des lieux des avoisinants consigné",
        "Photographic and written record agreed with each neighbour before work starts.": (
            "Relevé photographique et écrit convenu avec chaque riverain avant le début des travaux."
        ),
        "Neighbour notification letters issued": "Courriers d'information aux riverains envoyés",
        "Letters issued with the working hours, the contact number and the start date.": (
            "Courriers envoyés avec les horaires de travail, le numéro de contact et la date de démarrage."
        ),
        "Waiting on the authority; chased twice, no date given yet.": (
            "En attente de l'autorité ; relancée deux fois, aucune date communiquée."
        ),
        "Design information outstanding from the consultant.": "Informations de conception attendues du bureau d'études.",
        "Adjoining owner has not returned the signed agreement.": (
            "Le propriétaire voisin n'a pas retourné la convention signée."
        ),
        "Utility provider cannot attend before the target start date.": (
            "Le concessionnaire ne peut pas intervenir avant la date de démarrage visée."
        ),
        "Survey could not be completed in season; revised window agreed.": (
            "Inventaire non terminé en saison ; nouvelle fenêtre convenue."
        ),
        "Not applicable: the site is served by the existing permanent supply.": (
            "Sans objet : le chantier est desservi par le branchement définitif existant."
        ),
        "Not applicable: no adjoining boundary is oversailed on this site.": (
            "Sans objet : aucune limite voisine n'est survolée sur ce chantier."
        ),
        "Not applicable: works are wholly within the existing curtilage.": (
            "Sans objet : les travaux sont entièrement à l'intérieur de l'emprise existante."
        ),
        "Not applicable: no excavation below the founding level on this package.": (
            "Sans objet : aucune fouille sous le niveau de fondation dans ce lot."
        ),
    },
}


def site_prep_text(locale: str | None, text: str) -> str:
    """``text`` in the project's language; English and unlisted text pass through unchanged."""
    return PHRASES.get(language_of(locale), {}).get(text, text)
