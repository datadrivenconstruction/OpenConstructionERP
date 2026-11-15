# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""German and French wording of the temporary-works register the demo seeds, keyed by the English sentence."""

from __future__ import annotations

from app.core.demo_locale_text import language_of

PHRASES: dict[str, dict[str, str]] = {
    "de": {
        # locations and blocks
        "{block}, level {level}, grid {grid}": "{block}, Ebene {level}, Achse {grid}",
        "{block}, core walls, level {level}": "{block}, Kernwände, Ebene {level}",
        "{block}, grid {grid}": "{block}, Achse {grid}",
        "{block}, party wall, grid {grid}": "{block}, Gebäudetrennwand, Achse {grid}",
        "{block}, basement perimeter, grid {grid}": "{block}, Untergeschoss-Umfang, Achse {grid}",
        "{block}, services corridor": "{block}, Leitungsgang",
        "{block}, deep basement, grid {grid}": "{block}, tiefes Untergeschoss, Achse {grid}",
        "{block}, north elevation": "{block}, Nordfassade",
        "{block}, atrium, level {level}": "{block}, Atrium, Ebene {level}",
        "{block}, level {level}, east elevation": "{block}, Ebene {level}, Ostfassade",
        "{block}, street elevation": "{block}, Straßenfassade",
        "{block}, crane position, grid {grid}": "{block}, Kranstandort, Achse {grid}",
        "{block}, east gate standing": "{block}, Aufstellfläche am Osttor",
        "{block}, level {level}, slab perimeter": "{block}, Ebene {level}, Deckenrand",
        "{block}, level {level}, risers and stair cores": "{block}, Ebene {level}, Steigschächte und Treppenkerne",
        "{block}, pile caps, grid {grid}": "{block}, Pfahlkopfplatten, Achse {grid}",
        "{block}, basement, grid {grid}": "{block}, Untergeschoss, Achse {grid}",
        "{block}, highway boundary": "{block}, Straßengrenze",
        "{block}, site entrance": "{block}, Baustelleneinfahrt",
        "{block}, basement ramp": "{block}, Rampe ins Untergeschoss",
        "Block A": "Block A",
        "Core": "Kern",
        # items
        "Falsework to the transfer slab soffit": "Lehrgerüst unter der Unterseite der Abfangdecke",
        "Falsework to the transfer slab soffit. Design case: 24 kN/m2 wet concrete, 1.5 kN/m2 construction live load and a 10 percent dynamic allowance on placement. Props at 1.2 m centres on sole plates, bearing checked at 150 kN/m2.": (
            "Lehrgerüst unter der Unterseite der Abfangdecke. Lastfall: 24 kN/m2 Frischbeton, 1,5 kN/m2 "
            "Verkehrslast der Bauphase und 10 Prozent dynamischer Zuschlag beim Einbringen. Stützen im "
            "Abstand von 1,2 m auf Unterlegbohlen, Pressung für 150 kN/m2 nachgewiesen."
        ),
        "Falsework to the podium beam": "Lehrgerüst für den Podiumunterzug",
        "Falsework to the podium beam soffit. Design case: 31 kN/m of wet concrete and reinforcement on a 9.0 m span, plus a 0.5 kN/m2 horizontal notional load on the bracing. Foundations on a compacted piling mat.": (
            "Lehrgerüst unter dem Podiumunterzug. Lastfall: 31 kN/m aus Frischbeton und Bewehrung bei 9,0 m "
            "Spannweite, dazu 0,5 kN/m2 horizontale Ersatzlast auf der Aussteifung. Gründung auf einer "
            "verdichteten Arbeitsebene."
        ),
        "Wall formwork to the lift core": "Wandschalung für den Aufzugskern",
        "Panel formwork to the lift core walls. Design case: 60 kN/m2 concrete pressure at a 2.0 m/h placement rate and 15 degrees C, ties at 600 mm vertical centres. Working platform bracketed off the panels.": (
            "Rahmenschalung für die Wände des Aufzugskerns. Lastfall: 60 kN/m2 Frischbetondruck bei 2,0 m/h "
            "Steiggeschwindigkeit und 15 Grad C, Anker im vertikalen Abstand von 600 mm. Arbeitsbühne an den "
            "Schaltafeln eingehängt."
        ),
        "Column formwork, ground to first lift": "Stützenschalung, Erdgeschoss bis erster Betonierabschnitt",
        "Column formwork for the first lift. Design case: 80 kN/m2 concrete pressure on a full height pour, clamps at 450 mm centres over the bottom third. Plumbing props tied to cast-in anchors, not to the reinforcement.": (
            "Stützenschalung für den ersten Betonierabschnitt. Lastfall: 80 kN/m2 Frischbetondruck bei "
            "Betonieren über die volle Höhe, Zwingen im Abstand von 450 mm im unteren Drittel. "
            "Ausrichtstützen an einbetonierten Ankern befestigt, nicht an der Bewehrung."
        ),
        "Proprietary slab tables, typical floor": "Deckentische (Systemschalung), Regelgeschoss",
        "Proprietary table forms used within the supplier's published configuration. Design case: 10.5 kN/m2 total slab load at the standard leg spacing, no deviation from the standard arrangement permitted without a fresh design.": (
            "Systemtische innerhalb der veröffentlichten Konfiguration des Herstellers. Lastfall: 10,5 kN/m2 "
            "Gesamtlast der Decke bei Regelstützenabstand, keine Abweichung von der Regelanordnung ohne neue "
            "Bemessung zulässig."
        ),
        "Back-propping to the two floors below the pour": "Nachstützung der zwei Geschosse unter der Betonierdecke",
        "Back-propping to the two floors below the slab being cast. Design case: the wet slab load redistributed 60 / 40 over the two supporting floors, checked against the strength gain curve at seven days. Props aligned floor to floor.": (
            "Nachstützung der zwei Geschosse unter der zu betonierenden Decke. Lastfall: Last der "
            "Frischbetondecke im Verhältnis 60 / 40 auf die zwei tragenden Geschosse verteilt, gegen die "
            "Festigkeitsentwicklung nach sieben Tagen nachgewiesen. Stützen geschossweise fluchtend."
        ),
        "Propping to the ground slab under the crane track": "Abstützung der Bodenplatte unter der Kranfahrbahn",
        "Propping to the ground slab where the crawler crane tracks cross the basement. Design case: 45 kN wheel load with a 25 percent impact allowance, spread through a 2.4 m square mat onto the slab below.": (
            "Abstützung der Bodenplatte, wo die Raupenkranfahrbahn das Untergeschoss kreuzt. Lastfall: 45 kN "
            "Radlast mit 25 Prozent Stoßzuschlag, über eine quadratische Platte von 2,4 m auf die darunter "
            "liegende Decke verteilt."
        ),
        "Needle propping to the party wall": "Kopfbalkenabfangung der Gebäudetrennwand",
        "Needle propping to the party wall while the underpinning is cast. Design case: 42 kN/m of wall and floor load carried on needles at 1.5 m centres, with settlement monitoring on the adjoining structure at each stage.": (
            "Abfangung der Gebäudetrennwand mit Kopfbalken, während die Unterfangung betoniert wird. "
            "Lastfall: 42 kN/m Wand- und Deckenlast, abgetragen über Kopfbalken im Abstand von 1,5 m, mit "
            "Setzungsmessung am Nachbargebäude in jeder Bauphase."
        ),
        "Sheet-piled support to the basement excavation": "Spundwandverbau der Baugrube des Untergeschosses",
        "Sheet-piled support to the basement box. Design case: 6.5 m retained height with at-rest earth pressure, a 10 kPa surcharge from the site road and the water table at 2.0 m below ground. Single walar frame at 1.5 m depth.": (
            "Spundwandverbau der Untergeschoss-Baugrube. Lastfall: 6,5 m Stützhöhe mit Erdruhedruck, 10 kPa "
            "Auflast aus der Baustraße und Grundwasserstand 2,0 m unter Gelände. Einlagiger Gurtrahmen in "
            "1,5 m Tiefe."
        ),
        "Trench support to the incoming services run": "Grabenverbau für die Hausanschlussleitungen",
        "Trench boxes to the incoming services run. Design case: 2.8 m deep trench in firm cohesive ground with a 5 kPa plant surcharge at the edge. No excavation outside the supported length, spoil kept 1.5 m back.": (
            "Grabenverbaugeräte für die Hausanschlussleitungen. Lastfall: 2,8 m tiefer Graben in festem "
            "bindigem Boden mit 5 kPa Geräteauflast am Rand. Kein Aushub außerhalb der verbauten Länge, "
            "Aushubmaterial 1,5 m zurückgesetzt."
        ),
        "Piled wall with a single prop frame": "Bohrpfahlwand mit einlagiger Aussteifung",
        "Contiguous piled wall with a single propping frame. Design case: staged excavation to 8.0 m with prop preloading, checked for the temporary condition before the base slab acts. Movement triggers set at 10 mm amber and 15 mm red.": (
            "Überschnittene Bohrpfahlwand mit einlagigem Steifenrahmen. Lastfall: abschnittsweiser Aushub bis "
            "8,0 m mit Vorspannung der Steifen, für den Bauzustand nachgewiesen, bevor die Bodenplatte wirkt. "
            "Verformungsschwellen bei 10 mm gelb und 15 mm rot."
        ),
        "Independent tied scaffold to the north elevation": "Verankertes Fassadengerüst an der Nordfassade",
        "Independent tied access scaffold within the standard configuration. Design case: loading class 3 at 2.0 kN/m2, ties on a 4 m by 4 m pattern, tie pull-out tested to 6.1 kN. Sheeting not permitted without a fresh wind check.": (
            "Verankertes Arbeitsgerüst in der Regelausführung. Lastfall: Lastklasse 3 mit 2,0 kN/m2, Anker im "
            "Raster 4 m x 4 m, Ankerauszug mit 6,1 kN geprüft. Netze oder Planen nur nach neuem Windnachweis."
        ),
        "Birdcage scaffold to the atrium soffit": "Raumgerüst unter der Atriumdecke",
        "Birdcage scaffold giving access to the atrium soffit. Design case: 2.0 kN/m2 working platform with a single boarded lift in use at a time, standards at 1.8 m centres on sole boards spreading onto the finished slab.": (
            "Raumgerüst für den Zugang zur Atriumdecke. Lastfall: Arbeitsebene mit 2,0 kN/m2, jeweils nur eine "
            "belegte Lage in Benutzung, Ständer im Abstand von 1,8 m auf Unterlegbohlen, die in die fertige "
            "Decke verteilen."
        ),
        "Loading bay on the elevation scaffold": "Ladebühne am Fassadengerüst",
        "Loading bay formed in the elevation scaffold. Design case: 5.0 kN/m2 over the bay with a single stillage landed at a time, additional ties either side of the opening and the posted load limit displayed at the gate.": (
            "Ladebühne im Fassadengerüst. Lastfall: 5,0 kN/m2 über die Bühne, jeweils nur eine Palette "
            "abgesetzt, zusätzliche Anker beidseits der Öffnung und die zulässige Last am Tor ausgehängt."
        ),
        "Facade retention to the retained elevation": "Fassadenhaltekonstruktion der erhaltenen Straßenfassade",
        "Facade retention scheme holding the retained street elevation with the floors removed. Design case: wind load to a 50 year return period on the free-standing facade plus a 5 kN/m notional horizontal restraint. Movement monitored weekly.": (
            "Fassadenhaltekonstruktion, die die erhaltene Straßenfassade nach dem Rückbau der Geschosse "
            "hält. Lastfall: Windlast mit 50 Jahren Wiederkehrperiode auf die freistehende Fassade plus "
            "5 kN/m horizontale Ersatzhaltekraft. Verformungen wöchentlich gemessen."
        ),
        "Tower crane base and grillage": "Turmdrehkran-Fundament und Trägerrost",
        "Tower crane base slab and grillage. Design case: in-service and out-of-service overturning moments taken from the crane foundation loading sheet, bearing pressure checked at 200 kPa. Base not to be loaded before 28 day strength.": (
            "Fundamentplatte und Trägerrost des Turmdrehkrans. Lastfall: Kippmomente im Betrieb und außer "
            "Betrieb aus dem Fundamentlastblatt des Krans, Bodenpressung für 200 kPa nachgewiesen. Fundament "
            "erst nach Erreichen der 28-Tage-Festigkeit belasten."
        ),
        "Mobile crane outrigger mats at the east gate": "Abstützplatten für den Mobilkran am Osttor",
        "Outrigger mats for mobile crane lifts from the east gate standing. Design case: 320 kN outrigger reaction spread to 120 kPa on the mat footprint, with a 1.5 m stand-off kept from the basement wall and no set-up over the services trench.": (
            "Abstützplatten für Mobilkranhübe von der Aufstellfläche am Osttor. Lastfall: 320 kN "
            "Stützkraft, auf 120 kPa unter der Plattenfläche verteilt, 1,5 m Abstand zur Kellerwand und "
            "kein Aufstellen über dem Leitungsgraben."
        ),
        "Class A edge protection to the slab perimeter": "Seitenschutz Klasse A am Deckenrand",
        "Proprietary class A edge protection to the slab perimeter. Design case: 0.3 kN point load and 0.3 kN/m line load at the top rail. Post sockets cast in with the slab, no clamped posts on the edge beam.": (
            "Systemseitenschutz Klasse A am Deckenrand. Lastfall: 0,3 kN Einzellast und 0,3 kN/m Linienlast "
            "am Handlauf. Pfostenhülsen in die Decke einbetoniert, keine geklemmten Pfosten am Randbalken."
        ),
        "Stair opening and riser guarding": "Absicherung von Treppenöffnungen und Steigschächten",
        "Guarding to the stair openings and service risers. Design case: the same 0.3 kN point load as the perimeter, with covers rated for a 1.5 kN foot load and fixed down rather than laid loose.": (
            "Absicherung der Treppenöffnungen und Installationsschächte. Lastfall: dieselbe Einzellast von "
            "0,3 kN wie am Deckenrand, Abdeckungen für 1,5 kN Trittlast bemessen und befestigt statt lose "
            "aufgelegt."
        ),
        "Well-point dewatering to the pile cap excavation": "Brunnenabsenkung für die Pfahlkopfplatten-Baugrube",
        "Well-point dewatering to the pile cap excavation. Design case: drawdown to 1.0 m below formation with a recharge allowance, settlement monitoring on the adjacent terrace and discharge consented before pumping starts.": (
            "Absenkung mit Brunnenanlage für die Baugrube der Pfahlkopfplatten. Lastfall: Absenkung auf "
            "1,0 m unter Planum mit Zuschlag für Wiederauffüllung, Setzungsmessung an der Nachbarzeile und "
            "Einleiterlaubnis vor Pumpbeginn."
        ),
        "Sump pumping to the basement slab pour": "Pumpensumpf-Wasserhaltung für die Untergeschoss-Bodenplatte",
        "Sump pumping keeping the basement formation dry for the slab pour. Design case: 12 l/s peak inflow after rain with a standby pump on site, sumps kept outside the pour sequence and backfilled as the slab advances.": (
            "Pumpensumpf-Wasserhaltung, die das Planum des Untergeschosses für das Betonieren der Bodenplatte "
            "trocken hält. Lastfall: 12 l/s Spitzenzufluss nach Regen mit Reservepumpe vor Ort, Sümpfe außerhalb "
            "der Betonierfolge und mit dem Fortschritt der Platte verfüllt."
        ),
        "Site perimeter hoarding to the highway boundary": "Bauzaun entlang der Straßengrenze",
        "Site perimeter hoarding, 2.4 m plywood on posts. Design case: wind on a solid free-standing wall to the site's exposure, posts in concrete-filled sockets at 3.0 m centres. No signage boards fixed without a fresh wind check.": (
            "Bauzaun um die Baustelle, 2,4 m Sperrholz auf Pfosten. Lastfall: Wind auf eine geschlossene "
            "freistehende Wand entsprechend der Lage der Baustelle, Pfosten in betonverfüllten Hülsen im "
            "Abstand von 3,0 m. Keine Werbetafeln ohne neuen Windnachweis."
        ),
        "Pavement gantry at the site entrance": "Gehwegüberbauung an der Baustelleneinfahrt",
        "Pavement gantry keeping the footway open past the site entrance. Design case: 5.0 kN/m2 on the deck for material storage plus a 50 kN vehicle impact case on the kerbside legs, headroom held at 2.6 m.": (
            "Gehwegüberbauung, die den Gehweg an der Baustelleneinfahrt offen hält. Lastfall: 5,0 kN/m2 auf "
            "der Plattform für Materiallagerung plus 50 kN Fahrzeuganprall an den bordseitigen Stützen, "
            "Durchgangshöhe 2,6 m."
        ),
        "Temporary access ramp into the basement": "Provisorische Zufahrtsrampe ins Untergeschoss",
        "Temporary access ramp into the basement. Design case: a 32 t dumper at 1 in 8 gradient on compacted fill, edge kerbs to both sides and the running surface inspected after heavy rain.": (
            "Provisorische Zufahrtsrampe ins Untergeschoss. Lastfall: 32-t-Dumper bei 12,5 Prozent Gefälle "
            "auf verdichteter Schüttung, beidseitige Randborde, Fahrfläche nach Starkregen geprüft."
        ),
        # notes and permit conditions
        "Raised at the temporary works review. Design brief to follow.": (
            "Bei der Prüfung der Hilfskonstruktionen aufgenommen. Planungsvorgabe folgt."
        ),
        "Design brief issued to the temporary works designer.": "Planungsvorgabe an den Planer der Hilfskonstruktion ausgegeben.",
        "Design received and with the checker.": "Planung eingegangen und beim Prüfer.",
        "Check certificate received. Permit to load follows the inspection before use.": (
            "Prüfbescheinigung liegt vor. Die Belastungsfreigabe folgt der Abnahme vor Nutzung."
        ),
        "Permit to load issued. Inspection before use passed.": "Belastungsfreigabe erteilt. Abnahme vor Nutzung bestanden.",
        "Loaded in accordance with the permit and the loading sequence.": (
            "Belastet gemäß Freigabe und Belastungsfolge."
        ),
        "In use. Inspected weekly by the coordinator and after any high wind.": (
            "In Nutzung. Wöchentlich und nach jedem Sturm vom Koordinator geprüft."
        ),
        "Permit to strike issued against the concrete strength result.": (
            "Ausschalfreigabe auf Grundlage des Festigkeitsergebnisses erteilt."
        ),
        "Struck in the sequence on the striking drawing. Permit closed out.": (
            "In der Reihenfolge des Ausschalplans zurückgebaut. Freigabe abgeschlossen."
        ),
        "Removed from site and the register entry closed.": "Von der Baustelle entfernt, Registereintrag geschlossen.",
        "On hold pending a revised design after the change to the loading.": (
            "Zurückgestellt bis zu einer überarbeiteten Planung nach der Laständerung."
        ),
        "No loading beyond the design case. Props and ties not to be adjusted, removed or re-positioned under load. Any change of loading or sequence needs a fresh permit.": (
            "Keine Belastung über den Bemessungsfall hinaus. Stützen und Anker nicht unter Last verstellen, "
            "entfernen oder versetzen. Jede Änderung von Belastung oder Reihenfolge erfordert eine neue "
            "Freigabe."
        ),
        "Striking not to start before the cube result confirms the strength named in the design. Follow the striking sequence on the drawing. Back-props to remain until released separately.": (
            "Ausschalen erst, wenn das Würfelergebnis die in der Planung genannte Festigkeit bestätigt. "
            "Ausschalfolge nach Plan einhalten. Nachstützungen bleiben bis zur gesonderten Freigabe stehen."
        ),
        "Dismantle top down in the reverse of the erection sequence. Exclusion zone at ground level throughout. No component to be dropped or thrown.": (
            "Von oben nach unten in umgekehrter Aufbaureihenfolge abbauen. Sperrbereich am Boden während der "
            "gesamten Dauer. Kein Bauteil abwerfen oder werfen."
        ),
    },
    "fr": {
        "{block}, level {level}, grid {grid}": "{block}, niveau {level}, axes {grid}",
        "{block}, core walls, level {level}": "{block}, voiles du noyau, niveau {level}",
        "{block}, grid {grid}": "{block}, axes {grid}",
        "{block}, party wall, grid {grid}": "{block}, mur mitoyen, axes {grid}",
        "{block}, basement perimeter, grid {grid}": "{block}, périmètre du sous-sol, axes {grid}",
        "{block}, services corridor": "{block}, couloir technique",
        "{block}, deep basement, grid {grid}": "{block}, sous-sol profond, axes {grid}",
        "{block}, north elevation": "{block}, façade nord",
        "{block}, atrium, level {level}": "{block}, atrium, niveau {level}",
        "{block}, level {level}, east elevation": "{block}, niveau {level}, façade est",
        "{block}, street elevation": "{block}, façade sur rue",
        "{block}, crane position, grid {grid}": "{block}, emplacement de la grue, axes {grid}",
        "{block}, east gate standing": "{block}, aire de stationnement du portail est",
        "{block}, level {level}, slab perimeter": "{block}, niveau {level}, rive de dalle",
        "{block}, level {level}, risers and stair cores": "{block}, niveau {level}, gaines et cages d'escalier",
        "{block}, pile caps, grid {grid}": "{block}, chevêtres de pieux, axes {grid}",
        "{block}, basement, grid {grid}": "{block}, sous-sol, axes {grid}",
        "{block}, highway boundary": "{block}, limite de voirie",
        "{block}, site entrance": "{block}, entrée du chantier",
        "{block}, basement ramp": "{block}, rampe du sous-sol",
        "Block A": "Bloc A",
        "Block B": "Bloc B",
        "Block C": "Bloc C",
        "Core": "Noyau",
        "Falsework to the transfer slab soffit": "Étaiement sous la sous-face de la dalle de transfert",
        "Falsework to the transfer slab soffit. Design case: 24 kN/m2 wet concrete, 1.5 kN/m2 construction live load and a 10 percent dynamic allowance on placement. Props at 1.2 m centres on sole plates, bearing checked at 150 kN/m2.": (
            "Étaiement sous la sous-face de la dalle de transfert. Cas de calcul : béton frais 24 kN/m2, "
            "charge d'exploitation de chantier 1,5 kN/m2 et majoration dynamique de 10 pour cent à la mise "
            "en place. Étais à entraxe de 1,2 m sur semelles, portance vérifiée à 150 kN/m2."
        ),
        "Falsework to the podium beam": "Étaiement de la poutre du podium",
        "Falsework to the podium beam soffit. Design case: 31 kN/m of wet concrete and reinforcement on a 9.0 m span, plus a 0.5 kN/m2 horizontal notional load on the bracing. Foundations on a compacted piling mat.": (
            "Étaiement sous la poutre du podium. Cas de calcul : 31 kN/m de béton frais et d'armatures sur "
            "une portée de 9,0 m, plus une charge horizontale fictive de 0,5 kN/m2 sur le contreventement. "
            "Appuis sur une plateforme compactée."
        ),
        "Wall formwork to the lift core": "Coffrage des voiles du noyau d'ascenseur",
        "Panel formwork to the lift core walls. Design case: 60 kN/m2 concrete pressure at a 2.0 m/h placement rate and 15 degrees C, ties at 600 mm vertical centres. Working platform bracketed off the panels.": (
            "Coffrage par panneaux des voiles du noyau d'ascenseur. Cas de calcul : pression du béton de "
            "60 kN/m2 à une vitesse de montée de 2,0 m/h et 15 degrés C, tirants à entraxe vertical de "
            "600 mm. Plateforme de travail fixée sur les panneaux."
        ),
        "Column formwork, ground to first lift": "Coffrage des poteaux, du rez-de-chaussée à la première levée",
        "Column formwork for the first lift. Design case: 80 kN/m2 concrete pressure on a full height pour, clamps at 450 mm centres over the bottom third. Plumbing props tied to cast-in anchors, not to the reinforcement.": (
            "Coffrage des poteaux pour la première levée. Cas de calcul : pression du béton de 80 kN/m2 sur "
            "une coulée pleine hauteur, colliers à entraxe de 450 mm sur le tiers inférieur. Étais de "
            "réglage d'aplomb reliés à des ancrages noyés, pas aux armatures."
        ),
        "Proprietary slab tables, typical floor": "Tables de coffrage de dalle industrialisées, étage courant",
        "Proprietary table forms used within the supplier's published configuration. Design case: 10.5 kN/m2 total slab load at the standard leg spacing, no deviation from the standard arrangement permitted without a fresh design.": (
            "Tables de coffrage industrialisées utilisées dans la configuration publiée du fournisseur. Cas "
            "de calcul : charge totale de dalle de 10,5 kN/m2 à l'espacement de pieds standard, aucun écart "
            "par rapport à la disposition standard sans nouvelle étude."
        ),
        "Back-propping to the two floors below the pour": "Rétro-étaiement des deux niveaux sous la dalle coulée",
        "Back-propping to the two floors below the slab being cast. Design case: the wet slab load redistributed 60 / 40 over the two supporting floors, checked against the strength gain curve at seven days. Props aligned floor to floor.": (
            "Rétro-étaiement des deux niveaux sous la dalle en cours de coulage. Cas de calcul : charge de la "
            "dalle fraîche répartie 60 / 40 sur les deux niveaux porteurs, vérifiée avec la courbe de gain de "
            "résistance à sept jours. Étais alignés d'un niveau à l'autre."
        ),
        "Propping to the ground slab under the crane track": "Étaiement du dallage sous le chemin de roulement de la grue",
        "Propping to the ground slab where the crawler crane tracks cross the basement. Design case: 45 kN wheel load with a 25 percent impact allowance, spread through a 2.4 m square mat onto the slab below.": (
            "Étaiement du dallage là où les chenilles de la grue croisent le sous-sol. Cas de calcul : charge "
            "de 45 kN par appui avec majoration d'impact de 25 pour cent, répartie par un tapis carré de 2,4 m "
            "sur la dalle inférieure."
        ),
        "Needle propping to the party wall": "Reprise en sous-œuvre par aiguilles du mur mitoyen",
        "Needle propping to the party wall while the underpinning is cast. Design case: 42 kN/m of wall and floor load carried on needles at 1.5 m centres, with settlement monitoring on the adjoining structure at each stage.": (
            "Reprise du mur mitoyen par aiguilles pendant le coulage de la reprise en sous-œuvre. Cas de "
            "calcul : 42 kN/m de charge de mur et de plancher portée par des aiguilles à entraxe de 1,5 m, "
            "avec suivi des tassements de l'ouvrage voisin à chaque phase."
        ),
        "Sheet-piled support to the basement excavation": "Soutènement par palplanches de la fouille du sous-sol",
        "Sheet-piled support to the basement box. Design case: 6.5 m retained height with at-rest earth pressure, a 10 kPa surcharge from the site road and the water table at 2.0 m below ground. Single walar frame at 1.5 m depth.": (
            "Soutènement par palplanches de la fouille du sous-sol. Cas de calcul : hauteur soutenue de 6,5 m "
            "avec poussée des terres au repos, surcharge de 10 kPa due à la piste de chantier et nappe à 2,0 m "
            "sous le terrain. Un cadre de lierne à 1,5 m de profondeur."
        ),
        "Trench support to the incoming services run": "Blindage de la tranchée des réseaux entrants",
        "Trench boxes to the incoming services run. Design case: 2.8 m deep trench in firm cohesive ground with a 5 kPa plant surcharge at the edge. No excavation outside the supported length, spoil kept 1.5 m back.": (
            "Blindage de la tranchée des réseaux entrants. Cas de calcul : tranchée de 2,8 m de profondeur "
            "en sol cohésif ferme avec surcharge d'engins de 5 kPa en rive. Aucune fouille hors de la "
            "longueur blindée, déblais maintenus à 1,5 m."
        ),
        "Piled wall with a single prop frame": "Paroi de pieux sécants avec un niveau de butons",
        "Contiguous piled wall with a single propping frame. Design case: staged excavation to 8.0 m with prop preloading, checked for the temporary condition before the base slab acts. Movement triggers set at 10 mm amber and 15 mm red.": (
            "Paroi de pieux sécants avec un cadre de butons. Cas de calcul : terrassement par phases jusqu'à "
            "8,0 m avec précontrainte des butons, vérifié en phase provisoire avant que le radier ne "
            "travaille. Seuils de déplacement fixés à 10 mm (orange) et 15 mm (rouge)."
        ),
        "Independent tied scaffold to the north elevation": "Échafaudage indépendant ancré sur la façade nord",
        "Independent tied access scaffold within the standard configuration. Design case: loading class 3 at 2.0 kN/m2, ties on a 4 m by 4 m pattern, tie pull-out tested to 6.1 kN. Sheeting not permitted without a fresh wind check.": (
            "Échafaudage d'accès indépendant ancré, dans la configuration standard. Cas de calcul : classe de "
            "charge 3 à 2,0 kN/m2, ancrages en maille de 4 m par 4 m, arrachement des ancrages testé à "
            "6,1 kN. Bâchage interdit sans nouvelle vérification au vent."
        ),
        "Birdcage scaffold to the atrium soffit": "Échafaudage en volume sous le plafond de l'atrium",
        "Birdcage scaffold giving access to the atrium soffit. Design case: 2.0 kN/m2 working platform with a single boarded lift in use at a time, standards at 1.8 m centres on sole boards spreading onto the finished slab.": (
            "Échafaudage en volume donnant accès au plafond de l'atrium. Cas de calcul : plancher de travail "
            "de 2,0 kN/m2 avec un seul niveau planchéié utilisé à la fois, montants à entraxe de 1,8 m sur "
            "semelles répartissant sur la dalle finie."
        ),
        "Loading bay on the elevation scaffold": "Quai de chargement sur l'échafaudage de façade",
        "Loading bay formed in the elevation scaffold. Design case: 5.0 kN/m2 over the bay with a single stillage landed at a time, additional ties either side of the opening and the posted load limit displayed at the gate.": (
            "Quai de chargement aménagé dans l'échafaudage de façade. Cas de calcul : 5,0 kN/m2 sur le quai "
            "avec une seule palette déposée à la fois, ancrages supplémentaires de part et d'autre de "
            "l'ouverture et charge limite affichée à la barrière."
        ),
        "Facade retention to the retained elevation": "Maintien de façade pour l'élévation conservée",
        "Facade retention scheme holding the retained street elevation with the floors removed. Design case: wind load to a 50 year return period on the free-standing facade plus a 5 kN/m notional horizontal restraint. Movement monitored weekly.": (
            "Dispositif de maintien de la façade sur rue conservée après dépose des planchers. Cas de calcul : "
            "vent de période de retour 50 ans sur la façade autoportante plus un maintien horizontal fictif "
            "de 5 kN/m. Déplacements suivis chaque semaine."
        ),
        "Tower crane base and grillage": "Massif et longrines de la grue à tour",
        "Tower crane base slab and grillage. Design case: in-service and out-of-service overturning moments taken from the crane foundation loading sheet, bearing pressure checked at 200 kPa. Base not to be loaded before 28 day strength.": (
            "Massif et longrines de la grue à tour. Cas de calcul : moments de renversement en service et "
            "hors service tirés de la fiche de charges de fondation de la grue, contrainte sur le sol "
            "vérifiée à 200 kPa. Massif à ne pas charger avant la résistance à 28 jours."
        ),
        "Mobile crane outrigger mats at the east gate": "Plaques de calage de la grue mobile au portail est",
        "Outrigger mats for mobile crane lifts from the east gate standing. Design case: 320 kN outrigger reaction spread to 120 kPa on the mat footprint, with a 1.5 m stand-off kept from the basement wall and no set-up over the services trench.": (
            "Plaques de calage pour les levages à la grue mobile depuis l'aire du portail est. Cas de calcul : "
            "réaction de stabilisateur de 320 kN répartie à 120 kPa sous la plaque, avec un recul de 1,5 m "
            "par rapport au mur du sous-sol et aucune installation au-dessus de la tranchée des réseaux."
        ),
        "Class A edge protection to the slab perimeter": "Protection de rive de classe A en périphérie de dalle",
        "Proprietary class A edge protection to the slab perimeter. Design case: 0.3 kN point load and 0.3 kN/m line load at the top rail. Post sockets cast in with the slab, no clamped posts on the edge beam.": (
            "Protection de rive industrialisée de classe A en périphérie de dalle. Cas de calcul : charge "
            "ponctuelle de 0,3 kN et charge linéique de 0,3 kN/m sur la lisse haute. Douilles de poteaux "
            "noyées dans la dalle, pas de poteaux serrés sur la poutre de rive."
        ),
        "Stair opening and riser guarding": "Protection des trémies d'escalier et des gaines",
        "Guarding to the stair openings and service risers. Design case: the same 0.3 kN point load as the perimeter, with covers rated for a 1.5 kN foot load and fixed down rather than laid loose.": (
            "Protection des trémies d'escalier et des gaines techniques. Cas de calcul : même charge "
            "ponctuelle de 0,3 kN qu'en périphérie, couvercles dimensionnés pour une charge de pied de "
            "1,5 kN et fixés plutôt que simplement posés."
        ),
        "Well-point dewatering to the pile cap excavation": "Rabattement par pointes filtrantes de la fouille des chevêtres",
        "Well-point dewatering to the pile cap excavation. Design case: drawdown to 1.0 m below formation with a recharge allowance, settlement monitoring on the adjacent terrace and discharge consented before pumping starts.": (
            "Rabattement de nappe par pointes filtrantes pour la fouille des chevêtres de pieux. Cas de "
            "calcul : rabattement à 1,0 m sous le fond de fouille avec marge de réalimentation, suivi des "
            "tassements du bâti voisin et rejet autorisé avant le début du pompage."
        ),
        "Sump pumping to the basement slab pour": "Pompage en fond de fouille pour le radier du sous-sol",
        "Sump pumping keeping the basement formation dry for the slab pour. Design case: 12 l/s peak inflow after rain with a standby pump on site, sumps kept outside the pour sequence and backfilled as the slab advances.": (
            "Pompage en puisards maintenant à sec le fond de fouille du sous-sol pour le coulage du radier. "
            "Cas de calcul : débit de pointe de 12 l/s après pluie avec une pompe de secours sur place, "
            "puisards hors de la séquence de coulage et rebouchés à l'avancement du radier."
        ),
        "Site perimeter hoarding to the highway boundary": "Clôture de chantier en limite de voirie",
        "Site perimeter hoarding, 2.4 m plywood on posts. Design case: wind on a solid free-standing wall to the site's exposure, posts in concrete-filled sockets at 3.0 m centres. No signage boards fixed without a fresh wind check.": (
            "Clôture de chantier, contreplaqué de 2,4 m sur poteaux. Cas de calcul : vent sur un mur plein "
            "autoportant selon l'exposition du site, poteaux dans des fourreaux remplis de béton à entraxe "
            "de 3,0 m. Aucun panneau d'affichage fixé sans nouvelle vérification au vent."
        ),
        "Pavement gantry at the site entrance": "Passage couvert sur trottoir à l'entrée du chantier",
        "Pavement gantry keeping the footway open past the site entrance. Design case: 5.0 kN/m2 on the deck for material storage plus a 50 kN vehicle impact case on the kerbside legs, headroom held at 2.6 m.": (
            "Passage couvert maintenant le trottoir ouvert devant l'entrée du chantier. Cas de calcul : "
            "5,0 kN/m2 sur le tablier pour le stockage de matériaux plus un choc de véhicule de 50 kN sur "
            "les pieds côté chaussée, hauteur libre de 2,6 m."
        ),
        "Temporary access ramp into the basement": "Rampe d'accès provisoire vers le sous-sol",
        "Temporary access ramp into the basement. Design case: a 32 t dumper at 1 in 8 gradient on compacted fill, edge kerbs to both sides and the running surface inspected after heavy rain.": (
            "Rampe d'accès provisoire vers le sous-sol. Cas de calcul : tombereau de 32 t sur une pente de "
            "12,5 pour cent sur remblai compacté, bordures de chaque côté et surface de roulement contrôlée "
            "après de fortes pluies."
        ),
        "Raised at the temporary works review. Design brief to follow.": (
            "Relevé lors de la revue des ouvrages provisoires. Cahier des charges de conception à suivre."
        ),
        "Design brief issued to the temporary works designer.": (
            "Cahier des charges de conception transmis au concepteur des ouvrages provisoires."
        ),
        "Design received and with the checker.": "Étude reçue et chez le vérificateur.",
        "Check certificate received. Permit to load follows the inspection before use.": (
            "Attestation de vérification reçue. L'autorisation de chargement suit le contrôle avant utilisation."
        ),
        "Permit to load issued. Inspection before use passed.": (
            "Autorisation de chargement délivrée. Contrôle avant utilisation satisfaisant."
        ),
        "Loaded in accordance with the permit and the loading sequence.": (
            "Chargé conformément à l'autorisation et à la séquence de chargement."
        ),
        "In use. Inspected weekly by the coordinator and after any high wind.": (
            "En service. Contrôlé chaque semaine par le coordinateur et après tout vent fort."
        ),
        "Permit to strike issued against the concrete strength result.": (
            "Autorisation de décoffrage délivrée sur la base du résultat de résistance du béton."
        ),
        "Struck in the sequence on the striking drawing. Permit closed out.": (
            "Décoffré selon la séquence du plan de décoffrage. Autorisation clôturée."
        ),
        "Removed from site and the register entry closed.": "Évacué du chantier et ligne du registre clôturée.",
        "On hold pending a revised design after the change to the loading.": (
            "En attente d'une étude révisée après la modification des charges."
        ),
        "No loading beyond the design case. Props and ties not to be adjusted, removed or re-positioned under load. Any change of loading or sequence needs a fresh permit.": (
            "Aucun chargement au-delà du cas de calcul. Ne pas régler, retirer ni déplacer les étais et les "
            "ancrages sous charge. Toute modification de charge ou de séquence exige une nouvelle autorisation."
        ),
        "Striking not to start before the cube result confirms the strength named in the design. Follow the striking sequence on the drawing. Back-props to remain until released separately.": (
            "Ne pas décoffrer avant que le résultat sur cubes confirme la résistance indiquée dans l'étude. "
            "Suivre la séquence de décoffrage du plan. Les rétro-étais restent en place jusqu'à leur "
            "libération séparée."
        ),
        "Dismantle top down in the reverse of the erection sequence. Exclusion zone at ground level throughout. No component to be dropped or thrown.": (
            "Démonter de haut en bas dans l'ordre inverse du montage. Zone d'exclusion au sol pendant toute "
            "la durée. Aucun élément ne doit être jeté ni lâché."
        ),
    },
}


def temporary_works_text(locale: str | None, text: str) -> str:
    """``text`` in the project's language; English and unlisted text pass through unchanged."""
    return PHRASES.get(language_of(locale), {}).get(text, text)
