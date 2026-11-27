# Einreichungen: Zuständigkeit, Verteiler und Abschluss

Behalten Sie im Blick, wer eine Einreichung als Nächster bearbeiten muss, wer eine Kopie erhält und wann sie abgeschlossen ist.

Öffnen Sie **Dokumente > Einreichungen** und dann eine Einreichung.

## Übergeben

1. Wählen Sie unter **Zuständigkeit und Verteiler** im Feld **Ball in court** die Person, die als Nächste handeln muss. Ändern Sie die Zuständigkeit, sobald der Vorgang den Besitzer wechselt.
2. Tragen Sie alle, die die Einreichung zur Information erhalten sollen, in den **Verteiler** ein. Er erscheint am Vorgang als "Verteiler: Namen".
3. Sobald über die Einreichung entschieden ist (genehmigt, mit Anmerkungen genehmigt oder abgelehnt), schließen Sie sie mit **Schließen**. Das dürfen nur Rollen, die Einreichungen ändern dürfen.

Auswählbar sind nur Personen, die das Projekt öffnen können.

## Wovor die Prüfregeln warnen

- `submittal.ball_in_court_assigned`: Eine offene Einreichung hat keine zuständige Person.
- `submittal.distribution_present`: Eine offene Einreichung hat einen leeren Verteiler.
- `submittal.people_have_project_access`: Fehler, wenn die zuständige Person oder ein Verteilereintrag das Projekt nicht öffnen kann.
