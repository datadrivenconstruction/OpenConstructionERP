# Regeln für Geräte, Budget-Ledger und Datenqualität

Kurze Übersicht über Regeln, die als Fehler oder Warnung erscheinen. Warnungen blockieren die Arbeit nie; sie zeigen, was zu klären ist, bevor es teuer wird.

## Optionale Zusatzpakete

Die Basisinstallation deckt alles ab, außer zwei optionalen Paketen:

- `pip install "openconstructionerp[saml]"` ergänzt SAML-Single-Sign-on (die SAML-Option unter Einstellungen > Single Sign-on erscheint nach der Installation), siehe [SSO](../sso.de.md). OIDC braucht nichts Zusätzliches.
- `pip install "openconstructionerp[parquet]"` ergänzt `pyarrow` für Parquet-Datenfeeds, siehe [Datenfeeds](../data-feeds.de.md). Ohne das Paket antwortet ein `.parquet`-Feed mit einer klaren Meldung, die dieses Paket nennt, und Einstellungen > Datenfeeds blendet die Parquet-URL aus. CSV und JSON funktionieren weiter.

## Geräte

- Jedes Gerät gehört genau einem Mandanten (Ihrer Organisation). Andere Mandanten sehen es nie.
- Ein Gerät wird nur über eine datierte Miete (Start- und Enddatum) mit einem Projekt verknüpft. Eine unbefristete Projektzuordnung gibt es nicht.
- Zwei Mieten desselben Geräts mit zeitlicher Überschneidung werden abgelehnt, ein Gerät kann also nicht am selben Tag auf zwei Projekten sein. Eine der Mieten kürzen oder verschieben.

## Budget-Ledger: Funktionstrennung

In den Budget-Ledger-Einstellungen jedes Projekts gibt es **Funktionstrennung**, standardmäßig an. Solange sie an ist, darf wer eine Budgetumbuchung oder -änderung beantragt hat, sie nicht selbst genehmigen; eine zweite Person muss das tun. Das Abschalten erfordert die Berechtigung zur Kostenmodell-Verwaltung, wird protokolliert und passt nur für sehr kleine Teams.

## Warnungen

- **Mangelmeldung (NCR) ohne Ursachenanalyse geschlossen**: Das Schließen einer schwerwiegenden Mangelmeldung mit leerer Ursache erzeugt eine Warnung. Ursache eintragen, damit die Korrekturmaßnahme nachvollziehbar bleibt.
- **Versicherung oder Bürgschaft ohne Deckungssumme**: Eine Police oder Bürgschaft ohne Deckungssumme wird markiert. Die Summe eintragen, damit Risikoauswertungen vollständig sind.
- **Kalkulationspreis ohne Währung**: Ein Preis ohne Währung übernimmt die Basiswährung des Projekts und zeigt eine Warnung. Bitte prüfen, denn ein Preis in anderer Währung würde sonst falsch bewertet.

## Freigabelinks

Ein Freigabelink zu einer Datei schützt Dateiname und Details, bis der Besucher das Passwort eingibt, und ebenso nach Ablauf des Links. Ohne Berechtigung oder nach Ablauf sieht der Besucher nur eine neutrale Eingabeaufforderung oder einen Hinweis.

## US-Paket: Bauhandwerkerpfandrecht (Liens)

Das US-Paket führt Lien- und Anzeigevorschriften je Bundesstaat nur als Referenz auf. Fristen und Formulare ändern sich und hängen vom Vertrag ab; lassen Sie sie vor der Anwendung von einem Rechtsbeistand prüfen.
