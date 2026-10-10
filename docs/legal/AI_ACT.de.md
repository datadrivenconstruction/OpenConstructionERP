# KI in OpenConstructionERP: was die Software tut und was der Betreiber tut

Auch verfügbar auf [English](AI_ACT.md) und [Русский](AI_ACT.ru.md).
Bei Abweichungen gilt die englische Fassung.

Diese Seite beschreibt Tatsachen über die Software. Sie ist keine
Konformitätserklärung zur Verordnung (EU) 2024/1689 (KI-Verordnung). Bisher
ist keine harmonisierte Norm zur KI-Verordnung veröffentlicht, eine
Konformitätsaussage hätte heute also keine Grundlage, und wir treffen keine.

## Was wir als KI zählen

Als KI zählen wir eine Funktion, wenn sie Daten an ein Sprach-, Sprach-
erkennungs- oder Bildmodell sendet und dessen Antwort verwendet. Regelbasierte
Prüfungen, Vorlagen, Formeln, Statistik und Optimierung (etwa die
Validierung, Kostenverdichtung, Terminplanung und Risikobewertung) sind in
diesem Sinn keine KI, auch wenn Marketingtexte sie so nennen.

## Ohne konfigurierten Anbieter wird nichts gesendet

Die Software wird ohne Modellschlüssel ausgeliefert und kontaktiert von sich
aus keinen Modellanbieter. Ein Anbieter wird erst genutzt, wenn ein Betreiber
oder Nutzer einen Schlüssel hinterlegt, in den Einstellungen, in einer
Umgebungsvariable oder in `~/.openestimate/config.json`. Den Anbieter wählt
der Betreiber. Die Datenschutzerklärung, [PRIVACY.md](PRIVACY.md) Abschnitt 5,
nennt jeden Anbieter und seine Adresse.

Wenn Daten Ihr eigenes Netz nicht verlassen sollen, betreiben Sie ein lokales
Modell (Ollama oder vLLM) und wählen es als Anbieter. Texte verlassen Ihre
Infrastruktur über die KI-Funktionen dann nicht.

Zwei Ausnahmen:

- Die Spracherkennung für Telefonprotokoll und Sprachaufnahme läuft immer
  über OpenAI, unabhängig vom gewählten Anbieter, mit einem OpenAI-Schlüssel.
  Aufnahmen werden standardmäßig 90 Tage aufbewahrt
  (`OE_PHONELOG_AUDIO_RETENTION_DAYS`).
- Anfragen an OpenRouter tragen einen Header, der die Nutzung dieser Anwendung
  zuordnet. Es gelten Ihr Schlüssel, Ihr Konto und die Bedingungen von
  OpenRouter.

## Der Mensch bestätigt, das Modell schlägt vor

KI-Ergebnisse sind Vorschläge. In der Kalkulation zeigt eine vorgeschlagene
Änderung ihre Herkunft und die Konfidenz des Modells und wird erst übernommen,
wenn ein Mensch sie annimmt. Die Konfidenz ist die Selbsteinschätzung des
Modells, keine Messung.

Eine Funktion arbeitet anders: der Modul-Baukasten. Dort schreibt das Modell
eine Spezifikation, niemals Python-Code. Ein Mensch liest im Prüfschritt jede
erzeugte Datei und klickt auf Installieren, danach wirkt das Modul sofort.

## Was der Betreiber tun muss

Wenn Sie die Software für Ihre Organisation betreiben, sind Sie Betreiber.
Insbesondere entscheiden Sie:

- ob Sie KI überhaupt aktivieren, mit welchem Anbieter und Vertrag;
- ob Ihre Nutzung unter eine Hochrisiko-Kategorie der KI-Verordnung fällt,
  etwa wenn Sie Bewertungen der Software für Entscheidungen über einzelne
  Personen verwenden (die Software bewertet Arbeitspakete, Lieferanten und
  Organisationen, keine Personen, aber Ihre eingegebenen Daten bestimmen,
  was tatsächlich bewertet wird);
- wie Sie Ihre Beschäftigten und andere Betroffene informieren, auch Personen,
  deren Stimme in einem aufgezeichneten Gespräch zu hören ist;
- wie lange Sie KI-Ergebnisse bei Ihren Datensätzen aufbewahren.

## Kontakt

Fragen zu dieser Seite: info@datadrivenconstruction.io
