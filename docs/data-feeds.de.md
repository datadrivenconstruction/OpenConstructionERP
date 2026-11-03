# Datenfeeds: Excel oder Power BI anbinden

Datenfeeds sind schreibgeschuetzte, flache Tabellen ueber Projekte, LV-Positionen, Rechnungen, Bestellungen und Terminplan-Vorgaenge. Sie fuegen eine URL in Excel, Power Query oder ein beliebiges BI-Werkzeug ein und aktualisieren bei Bedarf. Zurueckschreiben ist nicht moeglich.

1. Einstellungen oeffnen, Reiter Datenfeeds.
2. Projekt waehlen (oder alle eigenen Projekte) und einen Schluessel mit dem Bereich `bi:read` erzeugen. Der Schluessel wird nur einmal angezeigt.
3. In Excel Daten > Aus dem Web und die CSV-URL einfuegen, oder den Power-Query-Ausschnitt der Seite nutzen, der den Schluessel im Header `X-API-Key` sendet.

Jeder Feed ist als `.csv` (UTF-8 mit BOM, oeffnet in Excel korrekt), `.parquet` und `.json` verfuegbar:

    /api/v1/bi-feed/feeds/<feed>.csv?project_id=<id>&updated_since=<ISO-Zeit>&limit=50000&offset=0

Feeds: `projects`, `boq_positions`, `invoices`, `purchase_orders`, `schedule_activities`. Geldbetraege und Mengen sind exakte Dezimalzahlen mit Waehrungsspalte, Datumsangaben ISO 8601 in UTC. Die Zeilen kommen in stabiler Reihenfolge. Grosse Feeds seitenweise mit `limit` (hoechstens 50000) und `offset` abrufen, oder dem Header `X-Next-After` mit `after=` folgen, damit bei neuen Zeilen nichts doppelt oder fehlend ist. Ein Feed ueber 500000 Zeilen muss seitenweise geladen werden.

Sie sehen nur Projekte, die Ihnen gehoeren oder in denen Sie Mitglied sind. Ein Schluessel ohne `bi:read` wird abgewiesen.

## SQL-Zugriff (optional, PostgreSQL 15 oder neuer)

    openconstructionerp bi enable --single-tenant
    openconstructionerp bi status
    openconstructionerp bi disable

`bi enable` legt das Schema `oe_bi` mit einer Sicht je Feed (gleiche Spaltennamen) und die schreibgeschuetzte Anmelderolle `oe_bi_reader` an. Das Passwort wird einmal ausgegeben und nicht gespeichert. `--single-tenant` nur verwenden, wenn die Instanz eine einzige Organisation bedient. Standardmaessig ist der Zugriff aus.
