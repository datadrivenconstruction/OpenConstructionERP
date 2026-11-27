# Kostenarten und Verpflichtungen

Budget, Obligo, Ist-Kosten und Prognose je Kostenstelle, aufgeteilt in Lohn, Material, Geräte, Nachunternehmer und Sonstiges. Jede Bestellposition und jeder Nachunternehmervertrag wird der Budgetzeile zugeordnet, die er verbraucht, und die Rechnungsprüfung stoppt eine Rechnung, die ihre Bestellung übersteigt.

Öffnen Sie **Kostensteuerung > Kostenmodell** und wählen Sie den Reiter **Nach Kostenart**.

## Budget nach Kostenart aufteilen

1. Erzeugen Sie das Budget aus dem Leistungsverzeichnis. Jede Position wird zu je einer Budgetzeile pro Kostenart, aufgeteilt nach den Ressourcen der Position.
2. Öffnen Sie **Nach Kostenart**. Die Zeilen sind Kostenstellen, jede Kostenart hat eine eigene Spaltengruppe, die letzte Zeile enthält die Summen. Die Spalten zeigen Budget, Obligo, Ist, Prognose, Endkostenprognose und Abweichung.
3. Fahren Sie über eine Zahl, um ihre Herkunft zu sehen, zum Beispiel die Bestellungen und Nachunternehmerverträge, die dieser Budgetzeile zugeordnet sind, oder ein von Hand eingetragenes Obligo.

Ein leeres Raster bedeutet, dass das Budget noch keine Zeilen hat; erzeugen Sie es zuerst aus dem Leistungsverzeichnis.

## Bestellungen und Verträge einer Budgetzeile zuordnen

1. Öffnen Sie eine Bestellung oder einen Nachunternehmervertrag.
2. Wählen Sie im Feld **Budgetzeile** jeder Position die Zeile, die sie verbraucht. Das Obligo fließt in diese Budgetzeile und erscheint im Raster.
3. Lassen Sie **Keiner Budgetzeile zugeordnet** stehen, wenn für die Ausgabe noch kein Budget besteht.

Das Feld ist mit Begründung als Tooltip deaktiviert für Rollen, die Budgetzeilen lesen, aber nicht ändern dürfen, und für bereits ausgegebene Bestellungen.

## Rechnungen gegen das Obligo

Bei der Freigabe einer Lieferantenrechnung vergleicht die Plattform sie mit der Bestellung oder dem Nachunternehmervertrag, den sie abrechnet. Die Freigabe wird verweigert, wenn die Rechnung das offene Obligo übersteigt (Bestell- oder Vertragswert plus genehmigte Änderungen, abzüglich bereits berechneter Beträge), in einer anderen Währung lautet, eine Lieferantenrechnungsnummer wiederholt oder vor ihrem Datum bezahlt wird. Eine Rechnung kann einen Nachunternehmervertrag verknüpfen; ein Sicherheitseinbehalt unter dem vereinbarten Anteil wird markiert. Das Formular zeigt das Obligo und den Grund, die Schaltfläche Freigeben ist mit diesem Grund deaktiviert. Das geplante Zahlungsdatum neben dem Fälligkeitsdatum lesen Zahlungsläufe und die Liquiditätsprognose zuerst.

## Wovor die Prüfregeln warnen

- `cost_types.position_unsplit`: Eine Position hatte keine Ressourcen, ihre Budgetzeile ging ungeteilt nach "Sonstiges".
- `cost_types.unknown_type`: Eine Budgetzeile hat eine Kategorie außerhalb von Lohn, Material, Geräte, Nachunternehmer und Sonstiges.
- `invoice_posting.*`: Rechnung über dem offenen Obligo, andere Währung, Einbehalt unter dem vereinbarten Anteil, doppelte oder möglicherweise doppelte Rechnungsnummer, Zahlungsdatum vor dem Rechnungsdatum.
