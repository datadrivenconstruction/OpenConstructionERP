# Hilfe bei Installation und Start

Auch verfügbar auf [English](INSTALL_TROUBLESHOOTING.md) und [Русский](INSTALL_TROUBLESHOOTING.ru.md).

Diese Seite hilft, wenn OpenConstructionERP bei der Installation oder beim Start eine Warnung oder einen Fehler zeigt. Suchen Sie die Meldung, die Sie sehen, lesen Sie, was sie bedeutet, und folgen Sie der dritten Zeile. Die meisten Fälle sind in einer Minute behoben, und keiner davon gefährdet Ihre Projekte.

Die Meldungen der App selbst erscheinen auf Englisch. Wir zitieren sie deshalb im Original. Meldungen von Windows und macOS erscheinen in der Sprache Ihres Systems.

Für eine normale Installation ohne Probleme siehe [Install OpenConstructionERP](desktop/INSTALL.md).

## Zuerst: die Protokolldateien

Wenn etwas schiefgeht, schreibt die App auf, was passiert ist. Wenn Sie uns schreiben, hängen Sie diese Dateien an. Damit finden wir die Ursache meist beim ersten Mal.

| Datei | Wo sie liegt | Was sie enthält |
|---|---|---|
| `desktop-launcher.log` | Windows: `C:\Users\<Ihr Name>\.openestimate\`<br>macOS und Linux: `~/.openestimate/` | Alles, was die Desktop-App beim Start getan hat |
| `backend-crash.log` | im Ordner `logs` Ihres Datenordners, also im selben `.openestimate`, sofern Sie `OE_DATA_DIR` nicht gesetzt haben | Details zu einem unerwarteten Stopp |
| `OpenConstructionERP-install-error.log` | Windows: `%TEMP%` (in die Adressleiste des Explorers eingeben) | Warum das Installationsprogramm abgebrochen hat |

Auf macOS und Linux ist `.openestimate` ein versteckter Ordner. Im Finder blenden Sie versteckte Ordner mit Cmd+Umschalt+. ein.

Wenn Sie mit pip installiert haben, führen Sie im Terminal `openconstructionerp doctor` aus. Der Befehl prüft die üblichen Probleme, etwa einen belegten Port oder eine fehlende Datenbank, und sagt zu jedem, was zu tun ist.

## Windows: bei der Installation

**Sie sehen:** ein blaues Fenster "Der Computer wurde durch Windows geschützt".
**Das heißt:** Das Installationsprogramm ist noch nicht codesigniert, Windows kennt den Herausgeber also nicht. Das ist eine Warnung, kein Virenfund.
**Was tun:** Klicken Sie auf **Weitere Informationen**, prüfen Sie, dass der Dateiname mit `OpenConstructionERP` beginnt, und klicken Sie auf **Trotzdem ausführen**. Details und eine Prüfung des Downloads stehen unter [Windows blockiert die App](desktop/WINDOWS_BLOCKED.de.md).

**Sie sehen:** Die intelligente App-Steuerung (Smart App Control) meldet, dass sie die App blockiert hat, oder die App lief einmal und wird seitdem bei jedem Start blockiert.
**Das heißt:** Die intelligente App-Steuerung von Windows 11 lehnt unsignierte Programme ab und bietet keine Schaltfläche zum Fortfahren.
**Was tun:** Folgen Sie [Windows blockiert die App](desktop/WINDOWS_BLOCKED.de.md). Dort steht, wie Sie herausfinden, welche Funktion blockiert hat, und wie Sie die App mit Docker oder WSL betreiben, während der Schutz eingeschaltet bleibt.

**Sie sehen:** "Please choose an installation folder whose path uses only Latin letters, digits and spaces. The built-in database cannot start from a folder with other characters in its path".
**Das heißt:** Der gewählte Ordnerpfad enthält Zeichen wie Umlaute, kyrillische oder chinesische Buchstaben. Die eingebaute Datenbank kann aus einem solchen Ordner nicht starten.
**Was tun:** Behalten Sie den vorgeschlagenen Ordner `C:\Program Files\OpenConstructionERP` oder wählen Sie einen wie `C:\OpenConstructionERP`. Bei einer stillen Installation (`/S`) zeigt das Programm dieselbe Meldung, endet mit Code 3 und schreibt den Grund nach `%TEMP%\OpenConstructionERP-install-error.log`.

**Sie sehen:** Die Installation bricht mit einem Fehler zu WebView2 ab.
**Das heißt:** Windows konnte Microsoft WebView2 nicht installieren, die Komponente, die das App-Fenster zeichnet. Das Installationsprogramm bringt sie mit, aber Windows muss sie annehmen.
**Was tun:** Starten Sie die Installation erneut. Scheitert sie wieder, installieren Sie "Microsoft Edge WebView2 Runtime" von der Microsoft-Website und starten Sie unser Installationsprogramm noch einmal.

**Sie sehen:** Ihr Virenschutz löscht eine Datei oder verschiebt sie während der Installation in die Quarantäne.
**Das heißt:** Das Programm ist neu und unsigniert, manche Virenschutzprogramme behandeln es deshalb misstrauisch.
**Was tun:** Prüfen Sie den Download wie unter [Windows blockiert die App](desktop/WINDOWS_BLOCKED.de.md) beschrieben. Ergibt die Prüfung `True`, stellen Sie die Datei aus der Quarantäne wieder her und erlauben Sie den Ordner `C:\Program Files\OpenConstructionERP`. Wenn Sie unsicher sind, schreiben Sie uns, bevor Sie etwas erlauben.

## Windows: Aktualisieren auf eine neue Version

**Sie sehen:** eine Seite mit der Frage, ob die installierte Version überschrieben oder zuerst entfernt werden soll, und darüber einen Satz, der zum Entfernen rät.
**Das heißt:** Dieser Satz stammt aus dem Baukasten des Installationsprogramms, wir können ihn nicht ändern.
**Was tun:** Lassen Sie die bereits ausgewählte Option (überschreiben) stehen. Das Installationsprogramm schließt die laufende App selbst und behält alle Ihre Projekte. Der erste Start nach einem Update kann länger dauern, während sich die Datenbank aktualisiert.

**Sie sehen:** Sie betreiben OpenConstructionERP auf demselben Rechner auch mit pip oder aus einem Terminal.
**Das heißt:** Beide nutzen denselben Ordner `.openestimate` und dieselbe Datenbank. Das Installationsprogramm hält diese Datenbank an, um die Programmdateien zu ersetzen, und damit fällt die Terminal-Version aus.
**Was tun:** Beenden Sie die Terminal-Version (Strg+C in ihrem Fenster) vor der Installation und starten Sie sie danach wieder.

**Sie sehen:** Mitten im Update erscheint das Deinstallationsfenster der alten Version.
**Das heißt:** Sie haben gewählt, die alte Version zuerst zu entfernen. Das funktioniert, dauert nur länger.
**Was tun:** Lassen Sie es durchlaufen. Das Kästchen "Delete the application data" können Sie leer lassen. Ihre Projekte entfernt es so oder so nicht.

## Windows: beim Start

**Sie sehen:** beim allerersten Start eine Minute oder länger den Ladebildschirm.
**Das heißt:** Die App legt ihre lokale Datenbank an. Das dauert einmalig etwa 40 bis 90 Sekunden, auf einer langsamen Festplatte länger.
**Was tun:** Warten Sie und schließen Sie das Fenster nicht. Spätere Starts sind schnell.

**Sie sehen:** ein Fenster "OpenConstructionERP failed to start", das eine Protokolldatei nennt.
**Das heißt:** Die App konnte ihr Fenster gar nicht öffnen.
**Was tun:** Starten Sie noch einmal. Kommt das Fenster wieder, senden Sie uns die genannte Protokolldatei.

**Sie sehen:** "The backend started, but the local database is not answering, so the app cannot open."
**Das heißt:** Die lokale Datenbank ist nicht hochgekommen, oft weil ein früherer Lauf nicht sauber beendet wurde.
**Was tun:** Starten Sie den Rechner neu und dann die App. Wiederholt es sich, senden Sie uns `desktop-launcher.log`.

**Sie sehen:** "The backend started, but this installation is missing the application files it serves".
**Das heißt:** Ein Teil des Programmordners fehlt, meist vom Virenschutz entfernt.
**Was tun:** Prüfen Sie die Quarantäne Ihres Virenschutzes und führen Sie das Installationsprogramm erneut über die bestehende Installation aus. Ihre Projekte bleiben unberührt.

**Sie sehen:** "The application backend did not start in time" oder "The application backend stopped responding while preparing the local database" (oder ein anderer Schritt).
**Das heißt:** Der Start hat länger gedauert, als die App wartet. Die Meldung nennt den Schritt.
**Was tun:** Schließen Sie das Fenster und starten Sie erneut. Ist die Festplatte langsam oder fast voll, schaffen Sie zuerst Platz. Bleibt es am selben Schritt hängen, senden Sie uns `desktop-launcher.log`.

**Sie sehen:** "The drive ran out of space while the application was starting" oder "There is not enough free space to start the application".
**Das heißt:** Genau das. Die Meldung nennt den Ordner und den freien Platz auf seinem Laufwerk.
**Was tun:** Schaffen Sie Platz auf diesem Laufwerk und starten Sie die App erneut.

**Sie sehen:** eine Meldung, dass der Ordner der lokalen Datenbank "sits too deep in the filesystem", mit zwei Zeichenzahlen.
**Das heißt:** Windows begrenzt die Länge eines vollständigen Dateipfads, und der Pfad Ihres Datenordners ist für die Datenbankdateien darin zu lang. Neu installieren hilft nicht, das Einschalten langer Pfade in Windows auch nicht.
**Was tun:** Verwenden Sie einen kürzeren Datenordner. Setzen Sie die Benutzer-Umgebungsvariable `OE_DATA_DIR` auf einen kurzen Pfad wie `C:\OpenConstructionERP\data` (Start, "Umgebungsvariablen" eingeben, "Umgebungsvariablen für dieses Konto bearbeiten", Neu) und starten Sie die App erneut. Im Terminal: `openconstructionerp serve --data-dir C:\OpenConstructionERP\data`.

**Sie sehen:** Ihr Windows-Benutzername enthält nicht-lateinische Buchstaben (zum Beispiel kyrillische oder chinesische), und Sie suchen Ihre Datenbank.
**Das heißt:** Aus einem solchen Pfad kann die Datenbank nicht arbeiten, deshalb liegt sie in `C:\ProgramData\OpenConstructionERP\clusters\<id>\pgdata`. Die Datei `pgdata.location` in Ihrem `.openestimate` nennt den genauen Ordner.
**Was tun:** Nichts zu reparieren. Für eine Sicherung kopieren Sie `.openestimate` und den in `pgdata.location` genannten Ordner.

**Sie sehen:** "The application backend stopped, restarting", und das Fenster lädt neu.
**Das heißt:** Der Hintergrundteil der App hat unerwartet angehalten, und die App hat ihn neu gestartet. Ihre gespeicherte Arbeit bleibt erhalten. Das geschieht höchstens zweimal in 30 Minuten.
**Was tun:** Arbeiten Sie weiter. Passiert es immer wieder, oder sehen Sie danach "The application backend has stopped", senden Sie uns `desktop-launcher.log` und `logs\backend-crash.log`.

**Sie sehen:** Nach einem Neustart sind Sie abgemeldet und die Sprache steht wieder auf Englisch.
**Das heißt:** Ein anderes Programm belegte den üblichen Port 8732 der App, also hat sie einen anderen gewählt. Die Fensteransicht behandelt einen anderen Port wie eine andere Website.
**Was tun:** Melden Sie sich erneut an. Damit es nicht wieder passiert, schließen Sie das andere Programm, das Port 8732 nutzt.

**Sie sehen:** "The application could not unpack itself into the temporary folder it uses."
**Das heißt:** Der Virenschutz hat Dateien beim Entpacken entfernt oder gesperrt, oder das Laufwerk mit dem temporären Ordner ist voll. Unter Windows betrifft das Versionen bis 18.4; ab 18.5 entpackt sich die Windows-App nicht mehr bei jedem Start.
**Was tun:** Schaffen Sie Platz auf diesem Laufwerk oder erlauben Sie die App im Virenschutz und starten Sie erneut.

## macOS

**Sie sehen:** Die `.dmg` lässt sich auf Ihrem Mac gar nicht öffnen.
**Das heißt:** Die Mac-Version ist nur für Apple Silicon (M1 und neuer). Für Intel-Macs gibt es keine.
**Was tun:** Auf einem Intel-Mac nutzen Sie pip oder Docker wie im README beschrieben.

**Sie sehen:** "OpenConstructionERP ist beschädigt und kann nicht geöffnet werden" oder "kann nicht geöffnet werden, da der Entwickler nicht verifiziert werden kann".
**Das heißt:** Die App ist von Apple noch nicht notarisiert, und macOS blockiert heruntergeladene Apps, die es nicht prüfen kann. Die App ist nicht beschädigt.
**Was tun:** Öffnen Sie das Terminal und führen Sie einmal aus:

```
xattr -dr com.apple.quarantine /Applications/OpenConstructionERP.app
```

Oder klicken Sie die App in "Programme" mit der rechten Maustaste an und wählen Sie **Öffnen**. Unter neuerem macOS gehen Sie zu **Systemeinstellungen**, **Datenschutz & Sicherheit**, scrollen nach unten und klicken auf **Dennoch öffnen**. Das ist nur einmal nötig.

## Linux

**Sie sehen:** Die `.deb` verlangt `libwebkit2gtk-4.1-0` oder lässt sich nicht installieren.
**Das heißt:** Die App braucht die Bibliothek WebKitGTK 4.1, um ihr Fenster zu zeichnen.
**Was tun:** Installieren Sie mit `sudo apt install ./OpenConstructionERP_*_amd64.deb`, das zieht die Bibliothek mit. Auf älteren Distributionen ohne Version 4.1 nutzen Sie das AppImage oder pip.

**Sie sehen:** Das AppImage tut beim Doppelklick nichts.
**Das heißt:** Die Datei ist noch nicht als Programm markiert.
**Was tun:** Führen Sie `chmod +x OpenConstructionERP*.AppImage` aus und starten Sie erneut.

**Sie sehen:** einen AppImage-Fehler, der FUSE oder `libfuse.so.2` erwähnt.
**Das heißt:** Neuere Distributionen installieren die FUSE-2-Bibliothek, die AppImages nutzen, nicht mehr.
**Was tun:** Installieren Sie sie, zum Beispiel `sudo apt install libfuse2` (unter Ubuntu 24.04 heißt das Paket `libfuse2t64`), oder nutzen Sie `.deb`, `.rpm` oder pip.

**Sie sehen:** Eine Version enthält kein AppImage.
**Das heißt:** Das AppImage wird getrennt gebaut und scheitert gelegentlich, während die anderen Dateien in Ordnung sind.
**Was tun:** Nutzen Sie `.deb` oder `.rpm` derselben Version.

## pip (jedes System)

**Sie sehen:** pip findet keine passende Version oder meldet, Python sei zu alt.
**Das heißt:** OpenConstructionERP braucht Python 3.12 oder neuer.
**Was tun:** Installieren Sie Python 3.12 oder neuer und führen Sie `python3.12 -m pip install --upgrade openconstructionerp` aus (unter Windows `py -3.12 -m pip ...`).

**Sie sehen:** "Port 8080 is already in use. Try: openconstructionerp serve --port 8081".
**Das heißt:** Ein anderes Programm nutzt Port 8080.
**Was tun:** Führen Sie den vorgeschlagenen Befehl aus und öffnen Sie die Adresse, die er ausgibt.

**Sie sehen:** Sie wissen nicht, wo Ihre Daten liegen.
**Das heißt:** pip legt alles in `.openestimate` in Ihrem Benutzerordner ab, demselben Ordner wie die Desktop-App.
**Was tun:** Um sie woanders abzulegen, starten Sie mit `openconstructionerp serve --data-dir <Ordner>` oder setzen `OE_DATA_DIR`.

## Docker

**Sie sehen:** http://localhost:8080 öffnet sich nicht.
**Das heißt:** Der Container läuft nicht, oder ein anderes Programm nutzt Port 8080.
**Was tun:** Führen Sie im Ordner mit `docker-compose.yml` `docker compose ps` und `docker compose logs app` aus, um den Grund zu sehen. Bewahren Sie die Datei `.env` in diesem Ordner gut auf: Sie enthält das Datenbankpasswort und den Anmeldeschlüssel.

## Deinstallieren und Ihre Daten

Die Deinstallation entfernt das Programm und behält Ihre Projekte. Sie liegen im Ordner `.openestimate` in Ihrem Benutzerordner (dazu der oben genannte `ProgramData`-Ordner, wenn Ihr Benutzername nicht-lateinische Buchstaben enthält). Eine Neuinstallation fängt deshalb nicht von vorn an. Für einen echten Neuanfang deinstallieren Sie und löschen `.openestimate` selbst, nachdem Sie es an einen sicheren Ort kopiert haben.

## Immer noch Probleme?

Schreiben Sie an info@datadrivenconstruction.io oder eröffnen Sie ein Issue unter [github.com/datadrivenconstruction/OpenConstructionERP/issues](https://github.com/datadrivenconstruction/OpenConstructionERP/issues). Bitte nennen Sie:

- die installierte Version und den Weg (Windows-Installationsprogramm, `.dmg`, `.deb`, `.rpm`, AppImage, pip oder Docker),
- Ihr System (Windows: Start, `winver` eingeben; macOS: Apple-Menü, Über diesen Mac),
- den genauen Text der Meldung oder einen Screenshot,
- die Protokolldateien vom Anfang dieser Seite.
