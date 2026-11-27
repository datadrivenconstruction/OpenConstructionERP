# CAD-Konvertierungswarteschlange und Konvertierungsfehler

Laden Sie eine Revit-, IFC- oder DWG-Datei hoch und sehen Sie, was der Konverter tut oder warum er nicht starten kann.

Öffnen Sie **BIM** und laden Sie das Modell hoch.

1. Laden Sie die Datei hoch. Es läuft jeweils ein Konverter, ein zweiter Upload zeigt daher **Warten auf den Konverter**, bis der erste fertig ist. Die Zahl paralleler Läufe steuert `OE_CONVERT_MAX_PARALLEL`.
2. Nach der Konvertierung öffnet sich das Modell. Ein Platzhaltermodell aus Quadern trägt einen Hinweis mit dem Grund: Der Konverter dieses Rechners hat keine Netze erzeugt, oder es ist kein Konverter installiert.
3. Steht der Status auf **Konverter erforderlich**, installieren Sie den in der Meldung genannten DDC-Konverter und laden Sie erneut hoch. Eine IFC-Datei wird immer über den DDC-Konverter gelesen; für echte IFC-Dateien gibt es keinen Rückfall auf einen Textparser.
4. Ein fehlgeschlagener Upload liefert eine verständliche Meldung für Netzwerkfehler, zu große Dateien und zu viele Anfragen, keinen rohen Fehlertext. Upload, Neuverarbeitung und Löschen sind für Rollen ausgeblendet, die der Server abweisen würde.

## Wovor die Prüfregeln warnen

- `bim.model.elements_have_category`: listet Elemente mit leerer oder unbekannter Kategorie.
- `bim.model.zero_quantities`: listet Elemente, deren Mengen alle null sind, oder warnt, wenn kein Element eine Menge hat.
