# Investitionsplan

Welche Projekte passen ins Budget, und was passiert, wenn wir eines verschieben.

Öffnen Sie **Portfolio > Capital plan** (`/capital-plan`). Das Modul gilt für jeden Eigentümer, jede Kommune und jeden Projektentwickler, die Projekte gegen ein begrenztes Jahresbudget reihen. Es enthält keine länderspezifische Logik; nationale Förderregeln gehören in ein Länderpaket.

## Einrichten

1. **Plan anlegen**: Name, Währung, Startjahr und Anzahl der Jahre (1 bis 15).
2. **Budget eintragen**: in der Zeile Envelope am Ende der Tabelle, eine Zahl je Jahr. Mehrere Finanzierungsquellen in einem Jahr (zum Beispiel Anleihe und Zuschuss) lassen sich über die API laden und werden als Summe angezeigt.
3. **Projekte importieren**: übernimmt die Projekte unter dem Portfolio-Knoten des Plans. Als Kosten gilt das zuletzt freigegebene Leistungsverzeichnis, sonst das Projektbudget, sonst der Vertragswert; Start und Dauer stammen aus den geplanten Terminen des Projekts. Alles lässt sich danach bearbeiten.

## Die Tabelle lesen

Jede Zeile ist ein Projekt, jede Spalte ein Jahr. Eine Zelle zeigt den Kostenanteil dieses Jahres (standardmäßig gleichmäßig verteilt, oder mit eigenen Anteilen je Jahr). Unter der Tabelle:

- **Envelope**: das verfügbare Geld im Jahr.
- **Demand**: die Kosten aller Projekte, die nicht zurückgestellt sind.
- **Gap**: Budget minus Bedarf. Rot bedeutet, dass das Jahr über dem Budget liegt.

## Was wäre wenn

Mit **New scenario** kopieren Sie das aktuelle Szenario, verschieben dann ein Startjahr mit den Pfeilen, ändern eine Priorität oder stellen ein Projekt zurück. Das Original bleibt unverändert. **Compare** zeigt die Änderung von Bedarf und Lücke je Jahr und die Projekte, deren Status oder Startjahr abweichen.

## Finanzierung vorschlagen

**Suggest funding** sortiert nach Priorität (1 ist die höchste), dann nach Punktzahl, dann nach Kosten und finanziert jedes Projekt, das in jedem Jahr seiner Ausgaben passt. Ein Projekt, das nicht passt, bleibt vorgeschlagen, mit dem ersten Jahr, das überläuft. Es ist ein Vorschlag mit Konfidenzwert: Nichts ändert sich, bis Sie **Apply** drücken.

## Prüfungen

Unter der Tabelle aufgelistet: Verteilung, die nicht 1 ergibt oder nicht zur Dauer passt, Ausgaben außerhalb der Planjahre, ein Jahr über dem Budget, ein Jahr ohne Budget, ein Projekt ohne Kosten, dasselbe Projekt doppelt in einem Szenario, eine zweite Basislinie und ein Projekt mit abweichender Währung.

## Export

**Export** lädt das Szenario als Excel-Datei mit den Jahren als Spalten herunter.

## Rechte

Wer lesen darf, sieht die Pläne. Änderungen erfordern die Rolle Manager.

## Nicht in dieser Version

Rangfolge nach Kapitalwert und internem Zinsfuß, Bewertungsmodelle mit mehreren Kriterien, nationale Förderregeln und Risikosimulation.
