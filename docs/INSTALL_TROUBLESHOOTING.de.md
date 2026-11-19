# Hilfe bei Installation und Start

Auch verfügbar auf [English](INSTALL_TROUBLESHOOTING.md) und [Русский](INSTALL_TROUBLESHOOTING.ru.md).

Diese Seite hilft, wenn Construction AI OS bei der Installation oder beim Start eine Warnung oder einen Fehler zeigt. Suchen Sie die Meldung, die Sie sehen, lesen Sie, was sie bedeutet, und folgen Sie der dritten Zeile. Die meisten Fälle sind in einer Minute behoben, und keiner davon gefährdet Ihre Projekte.

Die Meldungen der App selbst erscheinen auf Englisch. Wir zitieren sie deshalb im Original. Meldungen von Windows und macOS erscheinen in der Sprache Ihres Systems.

Für eine normale Installation ohne Probleme siehe [Install Construction AI OS](desktop/INSTALL.md).

## Zuerst: die Protokolldateien

Wenn etwas schiefgeht, schreibt die App auf, was passiert ist. Wenn Sie uns schreiben, hängen Sie diese Dateien an. Damit finden wir die Ursache meist beim ersten Mal.

| Datei | Wo sie liegt | Was sie enthält |
|---|---|---|
| `desktop-launcher.log` | Windows: `C:\Users\<Ihr Name>\.openestimate\`<br>macOS und Linux: `~/.openestimate/` | Alles, was die Desktop-App beim Start getan hat. Sie bleibt in Ihrem Benutzerordner, auch wenn `OE_DATA_DIR` die Daten verlegt |
| `backend-crash.log` | im Ordner `logs` Ihres Datenordners, also im selben `.openestimate`, sofern Sie `OE_DATA_DIR` nicht gesetzt haben | Details zu einem unerwarteten Stopp. Sie zieht mit `OE_DATA_DIR` um |
| Ordner `log` der Datenbank | `pgdata\log` in Ihrem Datenordner, standardmäßig also `.openestimate\pgdata\log`. Liegt in `.openestimate` eine Datei `pgdata.location`, der Ordner `log` in dem dort genannten Ordner | Warum die eingebaute Datenbank nicht gestartet ist |
| `OpenConstructionERP-install-error.log` | Windows: `%TEMP%` (in die Adressleiste des Explorers eingeben) | Warum das Installationsprogramm abgebrochen hat |

Auf macOS und Linux ist `.openestimate` ein versteckter Ordner. Im Finder blenden Sie versteckte Ordner mit Cmd+Umschalt+. ein.

Wenn Sie mit pip installiert haben, führen Sie im Terminal `openconstructionerp doctor` aus. Der Befehl prüft die üblichen Probleme, etwa einen belegten Port oder eine fehlende Datenbank, und sagt zu jedem, was zu tun ist.

## Windows: bei der Installation

**Sie sehen:** ein blaues Fenster "Der Computer wurde durch Windows geschützt".
**Das heißt:** Das Installationsprogramm ist noch nicht codesigniert, Windows kennt den Herausgeber also nicht. Das ist eine Warnung, kein Virenfund.
**Was tun:** Klicken Sie auf **Weitere Informationen**, prüfen Sie, dass der Dateiname mit `Construction AI OS` beginnt, und klicken Sie auf **Trotzdem ausführen**. Details und eine Prüfung des Downloads stehen unter [Windows blockiert die App](desktop/WINDOWS_BLOCKED.de.md).

**Sie sehen:** Die intelligente App-Steuerung (Smart App Control) meldet, dass sie die App blockiert hat, oder die App lief einmal und wird seitdem bei jedem Start blockiert.
**Das heißt:** Die intelligente App-Steuerung von Windows 11 lehnt unsignierte Programme ab und bietet keine Schaltfläche zum Fortfahren.
**Was tun:** Folgen Sie [Windows blockiert die App](desktop/WINDOWS_BLOCKED.de.md). Dort steht, wie Sie herausfinden, welche Funktion blockiert hat, und wie Sie die App mit Docker oder WSL betreiben, während der Schutz eingeschaltet bleibt.

**Sie sehen:** "Please choose an installation folder whose path uses only Latin letters, digits and spaces. The built-in database cannot start from a folder with other characters in its path".
**Das heißt:** Der gewählte Ordnerpfad enthält Zeichen wie Umlaute, kyrillische oder chinesische Buchstaben. Die eingebaute Datenbank kann aus einem solchen Ordner nicht starten.
**Was tun:** Behalten Sie den vorgeschlagenen Ordner `C:\Program Files\Construction AI OS` oder wählen Sie einen wie `C:\Construction AI OS`. Bei einer stillen Installation (`/S`) zeigt das Programm dieselbe Meldung, endet mit Code 3 und schreibt den Grund nach `%TEMP%\OpenConstructionERP-install-error.log`.

**Sie sehen:** Die Installation bricht mit einem Fehler zu WebView2 ab.
**Das heißt:** Windows konnte Microsoft WebView2 nicht installieren, die Komponente, die das App-Fenster zeichnet. Das Installationsprogramm bringt sie mit, eine Internetverbindung ist also nicht nötig; der Fehler kommt von Windows selbst, etwa durch eine Richtlinie, ein ausstehendes Update oder ein beschädigtes früheres WebView2.
**Was tun:** Starten Sie den Rechner neu und dann die Installation erneut. Scheitert sie wieder, installieren Sie "Microsoft Edge WebView2 Runtime" von der Microsoft-Website und starten Sie unser Installationsprogramm noch einmal.

**Sie sehen:** Ihr Virenschutz löscht eine Datei oder verschiebt sie während der Installation in die Quarantäne.
**Das heißt:** Das Programm ist neu und unsigniert, manche Virenschutzprogramme behandeln es deshalb misstrauisch.
**Was tun:** Prüfen Sie den Download wie unter [Windows blockiert die App](desktop/WINDOWS_BLOCKED.de.md) beschrieben. Ergibt die Prüfung `True`, stellen Sie die Datei aus der Quarantäne wieder her und erlauben Sie den Ordner `C:\Program Files\Construction AI OS`. Wenn Sie unsicher sind, schreiben Sie uns, bevor Sie etwas erlauben.

## Windows: Aktualisieren auf eine neue Version

**Sie sehen:** eine Seite mit der Frage, ob die installierte Version überschrieben oder zuerst entfernt werden soll, und darüber einen Satz, der zum Entfernen rät.
**Das heißt:** Dieser Satz stammt aus dem Baukasten des Installationsprogramms, wir können ihn nicht ändern.
**Was tun:** Lassen Sie die bereits ausgewählte Option (überschreiben) stehen. Das Installationsprogramm schließt die laufende App selbst und behält alle Ihre Projekte. Der erste Start nach einem Update kann länger dauern, während sich die Datenbank aktualisiert.

**Sie sehen:** Sie betreiben Construction AI OS auf demselben Rechner auch mit pip oder aus einem Terminal.
**Das heißt:** Beide nutzen denselben Ordner `.openestimate` und dieselbe Datenbank. Das Installationsprogramm hält diese Datenbank an, um die Programmdateien zu ersetzen, und damit fällt die Terminal-Version aus. Beim Update von 18.4.0 schließt das alte Deinstallationsprogramm außerdem jedes Programm namens `openconstructionerp.exe`, also auch eine mit pip gestartete Terminal-Version.
**Was tun:** Beenden Sie die Terminal-Version (Strg+C in ihrem Fenster) vor der Installation und starten Sie sie danach wieder.

**Sie sehen:** Mitten im Update erscheint das Deinstallationsfenster der alten Version.
**Das heißt:** Sie haben gewählt, die alte Version zuerst zu entfernen. Das funktioniert, dauert nur länger.
**Was tun:** Lassen Sie es durchlaufen. Das Kästchen "Delete the application data" können Sie leer lassen. Es entfernt nur, was das App-Fenster speichert, Ihre Anmeldung und die gewählte Sprache (in `%APPDATA%` und `%LOCALAPPDATA%\io.openconstructionerp.desktop`), niemals Ihre Projekte.

## Desktop-App: beim Start

**Sie sehen:** beim allerersten Start eine Minute oder länger den Ladebildschirm.
**Das heißt:** Die App legt ihre lokale Datenbank an. Das dauert einmalig ein bis zwei Minuten, auf einer langsamen Festplatte länger.
**Was tun:** Warten Sie und schließen Sie das Fenster nicht. Spätere Starts sind schnell.

**Sie sehen:** ein Fenster "Construction AI OS failed to start", das eine Protokolldatei nennt.
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
**Was tun:** Verwenden Sie einen kürzeren Datenordner. Setzen Sie die Benutzer-Umgebungsvariable `OE_DATA_DIR` auf einen kurzen Pfad wie `C:\cao-data` (Start, "Umgebungsvariablen" eingeben, "Umgebungsvariablen für dieses Konto bearbeiten", Neu) und starten Sie die App erneut. Im Terminal: `openconstructionerp serve --data-dir C:\cao-data`.

**Sie sehen:** Ihr Windows-Benutzername enthält nicht-lateinische Buchstaben (zum Beispiel kyrillische oder chinesische), und Sie suchen Ihre Datenbank.
**Das heißt:** Aus einem solchen Pfad kann die Datenbank nicht arbeiten, deshalb liegt sie in `C:\ProgramData\OpenConstructionERP\clusters\<id>\pgdata`. Die Datei `pgdata.location` in Ihrem `.openestimate` nennt den genauen Ordner.
**Was tun:** Nichts zu reparieren. Für eine Sicherung kopieren Sie `.openestimate` und den in `pgdata.location` genannten Ordner.

**Sie sehen:** "The application backend stopped, restarting", und das Fenster lädt neu.
**Das heißt:** Der Hintergrundteil der App hat unerwartet angehalten, und die App hat ihn neu gestartet. Ihre gespeicherte Arbeit bleibt erhalten. Das geschieht höchstens zweimal in 30 Minuten.
**Was tun:** Arbeiten Sie weiter. Passiert es immer wieder, oder sehen Sie danach "The application backend has stopped", senden Sie uns `desktop-launcher.log` und `logs\backend-crash.log`.

**Sie sehen:** Bei jedem Start der App sind Sie abgemeldet und die Sprache steht wieder auf Englisch.
**Das heißt:** Ein anderes Programm belegt Port 8732, den Port, den die App normalerweise nutzt. Version 18.5.0 wählt dann bei jedem Start einen zufälligen freien Port, und das App-Fenster behandelt jeden neuen Port wie eine neue Website, findet also Ihre Anmeldung und Sprache nicht. Ihre Projekte sind nicht betroffen.
**Was tun:** Schließen Sie das andere Programm, das Port 8732 nutzt, oder stellen Sie es um. Unter Windows zeigt `netstat -ano | findstr :8732` im Terminal seine Prozess-ID, und der Task-Manager listet diese ID unter Details.

**Sie sehen:** "The application never finished unpacking itself, so its backend never started." oder "The application could not unpack itself into the temporary folder it uses."
**Das heißt:** Unter macOS und Linux entpackt die App ihr Backend bei jedem Start in einen temporären Ordner, wie es die Windows-App bis 18.4 tat. Ein langsames oder volles Laufwerk oder ein Virenschutz, der die Dateien entfernt oder sperrt, verhindert das. Ab 18.5 entpackt sich die Windows-App nicht mehr.
**Was tun:** Schaffen Sie Platz auf diesem Laufwerk oder erlauben Sie die App im Virenschutz und starten Sie erneut.

**Sie sehen:** Sie betreiben bereits PostgreSQL auf Port 5432 und befürchten einen Konflikt mit der App.
**Das heißt:** Es gibt keinen. Die eingebaute Datenbank nimmt unter Windows einen zufälligen freien lokalen Port und lauscht unter macOS und Linux nur auf einem lokalen Socket.
**Was tun:** Nichts.

## macOS

**Sie sehen:** Die App läuft auf Ihrem Mac gar nicht.
**Das heißt:** Die Mac-Version ist nur für Apple Silicon (M1 und neuer). Für Intel-Macs gibt es keine.
**Was tun:** Auf einem Intel-Mac nutzen Sie pip oder Docker wie im README beschrieben.

**Sie sehen:** "Construction AI OS ist beschädigt und kann nicht geöffnet werden" oder "kann nicht geöffnet werden, da der Entwickler nicht verifiziert werden kann".
**Das heißt:** Die App ist von Apple noch nicht notarisiert, und macOS blockiert heruntergeladene Apps, die es nicht prüfen kann. Die App ist nicht beschädigt.
**Was tun:** Öffnen Sie das Terminal und führen Sie einmal aus:

```
xattr -dr com.apple.quarantine "/Applications/Construction AI OS.app"
```

Oder klicken Sie die App in "Programme" mit der rechten Maustaste an und wählen Sie **Öffnen**. Unter neuerem macOS gehen Sie zu **Systemeinstellungen**, **Datenschutz & Sicherheit**, scrollen nach unten und klicken auf **Dennoch öffnen**. Das ist nur einmal nötig.

## Linux

**Sie sehen:** Die `.deb` verlangt `libwebkit2gtk-4.1-0` oder lässt sich nicht installieren.
**Das heißt:** Die App braucht die Bibliothek WebKitGTK 4.1, um ihr Fenster zu zeichnen.
**Was tun:** Installieren Sie mit `sudo apt install ./construction-ai-os_*_amd64.deb`, das zieht die Bibliothek mit. Bietet Ihre Distribution kein `libwebkit2gtk-4.1-0` (Ubuntu älter als 22.04, Debian älter als 12), nutzen Sie pip.

**Sie sehen:** Die `.rpm` lässt sich nicht installieren oder meldet fehlende Abhängigkeiten.
**Das heißt:** `rpm -i` installiert die Bibliotheken nicht, die die App braucht.
**Was tun:** Installieren Sie mit `sudo dnf install ./construction-ai-os-*.x86_64.rpm`, das zieht sie mit.

**Sie sehen:** Das AppImage tut beim Doppelklick nichts.
**Das heißt:** Die Datei ist noch nicht als Programm markiert.
**Was tun:** Führen Sie `chmod +x "Construction AI OS"*.AppImage` aus und starten Sie erneut.

**Sie sehen:** einen AppImage-Fehler, der FUSE oder `libfuse.so.2` erwähnt.
**Das heißt:** Neuere Distributionen installieren die FUSE-2-Bibliothek, die AppImages nutzen, nicht mehr.
**Was tun:** Installieren Sie sie, zum Beispiel `sudo apt install libfuse2` (unter Ubuntu 24.04 heißt das Paket `libfuse2t64`), oder nutzen Sie `.deb`, `.rpm` oder pip.

**Sie sehen:** Eine Version enthält kein AppImage.
**Das heißt:** Das AppImage wird getrennt gebaut und scheitert gelegentlich, während die anderen Dateien in Ordnung sind.
**Was tun:** Nutzen Sie `.deb` oder `.rpm` derselben Version.

## pip (jedes System)

**Sie sehen:** pip findet keine passende Version oder meldet, Python sei zu alt.
**Das heißt:** Construction AI OS braucht Python 3.12 oder neuer.
**Was tun:** Installieren Sie Python 3.12 oder neuer und führen Sie `python3.12 -m pip install --upgrade openconstructionerp` aus (unter Windows `py -3.12 -m pip ...`).

**Sie sehen:** `error: externally-managed-environment` (Ubuntu ab 23.04, Debian ab 12).
**Das heißt:** Das System-Python lässt pip nicht hineininstallieren.
**Was tun:** Nutzen Sie `pipx install openconstructionerp` oder legen Sie zuerst eine virtuelle Umgebung an: `python3 -m venv ~/oe && ~/oe/bin/pip install openconstructionerp`. Details stehen in [Installing on Linux](INSTALL_LINUX.md).

**Sie sehen:** `openconstructionerp` wird nicht erkannt, oder command not found.
**Das heißt:** Der Ordner, in den pip Befehle legt, steht nicht im PATH, was unter Windows häufig ist.
**Was tun:** Führen Sie stattdessen `python -m openconstructionerp` aus. Das funktioniert auf jedem System, ohne PATH anzufassen.

**Sie sehen:** "Port 8080 is already in use. Try: openconstructionerp serve --port 8081".
**Das heißt:** Ein anderes Programm nutzt Port 8080.
**Was tun:** Führen Sie den vorgeschlagenen Befehl aus und öffnen Sie die Adresse, die er ausgibt.

**Sie sehen:** "Embedded PostgreSQL could not start".
**Das heißt:** Die eingebaute Datenbank ist nicht gestartet. Die Meldung nennt den Ordner mit ihrem Protokoll.
**Was tun:** Führen Sie `openconstructionerp doctor` aus. Hilft das nicht, installieren Sie mit `pip install --upgrade --force-reinstall openconstructionerp` neu und senden Sie uns das genannte Protokoll.

**Sie sehen:** Sie wissen nicht, wo Ihre Daten liegen.
**Das heißt:** pip legt alles in `.openestimate` in Ihrem Benutzerordner ab, demselben Ordner wie die Desktop-App.
**Was tun:** Um sie woanders abzulegen, starten Sie mit `openconstructionerp serve --data-dir <Ordner>` oder setzen `OE_DATA_DIR`.

## Docker

**Sie sehen:** Compose bricht mit "POSTGRES_PASSWORD must be set" oder "JWT_SECRET must be set" ab.
**Das heißt:** Die Datei `.env` mit den beiden Schlüsseln fehlt oder liegt nicht im Ordner mit `docker-compose.yml`.
**Was tun:** Legen Sie sie in diesem Ordner an, wie in [Getting started](getting-started.md#path-c-docker) gezeigt. Unter Windows nutzen Sie die PowerShell-Befehle von dort, denn ein einfaches `>` in Windows PowerShell schreibt eine Datei, die Compose nicht lesen kann.

**Sie sehen:** http://localhost:8080 öffnet sich nicht.
**Das heißt:** Der Container läuft nicht, oder ein anderes Programm nutzt Port 8080.
**Was tun:** Führen Sie im Ordner mit `docker-compose.yml` `docker compose ps` und `docker compose logs app` aus, um den Grund zu sehen. Für einen anderen Port starten Sie mit `OE_PORT=8081 OE_ALLOWED_ORIGINS=http://localhost:8081 docker compose up -d` und öffnen http://localhost:8081. Bewahren Sie die Datei `.env` in diesem Ordner gut auf: Sie enthält das Datenbankpasswort und den Anmeldeschlüssel.

**Sie sehen:** Auf einem Mac mit Apple Silicon oder einem anderen ARM-Rechner warnt Docker, dass die Image-Plattform `linux/amd64` nicht passt, oder die App ist sehr langsam.
**Das heißt:** Das veröffentlichte Image ist nur für x86-64 gebaut.
**Was tun:** Bauen Sie aus dem Quellcode mit `make quickstart`, oder nutzen Sie pip.

## Anmelden bei einer Installation, die Sie selbst betreiben

**Sie sehen:** "Invalid email or password" bei einem Konto, das Sie gerade angelegt haben, und beim erneuten Anlegen steht dort "Email already registered".
**Das heißt:** Das Konto existiert und wartet darauf, dass eine Administratorin oder ein Administrator es freischaltet. Installationen nutzen standardmäßig `OE_REGISTRATION_MODE=admin-approve`; dabei wird jedes Konto außer dem allerersten auf einer leeren Datenbank als inaktiv gespeichert. Das erste Konto auf einer wirklich leeren Datenbank wird automatisch aktiviert und wird zum Administrator; wenn nicht, lag schon etwas in der Datenbank: Demo-Daten, ein Konto aus einem früheren Lauf oder ein Datenordner, den der Server weiter liest.
**Was tun:** Wählen Sie einen dieser drei Wege.

- Sie betreiben die Installation selbst und möchten, dass Konten sofort nach dem Anlegen funktionieren: Starten Sie den Server mit der Umgebungsvariablen `OE_REGISTRATION_MODE` auf `open`. In Windows PowerShell schreiben Sie `$env:OE_REGISTRATION_MODE="open"` in die Zeile direkt vor der, die ihn startet; in einer Linux- oder macOS-Shell exportieren Sie sie zuerst auf dieselbe Weise. Unter Docker tragen Sie `OE_REGISTRATION_MODE=open` in die Datei `.env` im Ordner mit `docker-compose.yml` ein, denn das ist die Datei, die Compose liest. Eine Datei `.env` in Ihrem Datenordner wird nicht gelesen: Die Datei, nach der das Programm sucht, liegt neben dem installierten Paket, bei einer pip-Installation also in Ihrer Python-Umgebung. Die Variable in der Umgebung zu setzen, aus der Sie starten, ist deshalb der Weg, der überall funktioniert.
- Sie sind die Administratorin oder der Administrator und möchten ein Konto freischalten: Melden Sie sich als Administrator an, öffnen Sie in der Seitenleiste **Benutzer** (die Seite **Benutzerverwaltung**) und drücken Sie in dieser Zeile **Aktivieren**. Das Team-Panel in den Einstellungen zeigt, wer wartet, trägt den Schalter aber nicht; es verlinkt hierher.
- Es kann sich auch niemand als Administrator anmelden: Nutzen Sie die Wiederherstellungsbefehle unten. Sie funktionieren offline, direkt am Datenordner, ohne laufenden Server und ohne versandte E-Mail.

**Sie sehen:** Sie kommen nicht hinein, kennen das Passwort nicht mehr, und es gibt keinen Mailserver, der einen Link zum Zurücksetzen schicken könnte.
**Das heißt:** Mit der Installation ist nichts falsch; das Passwort ist schlicht nicht wiederherstellbar, weil nur sein Hash gespeichert ist.
**Was tun:** Setzen Sie ein neues in einem Terminal, in derselben Umgebung, aus der Sie den Server starten:

```
openconstructionerp reset-password you@example.com
```

Der Befehl fragt das neue Passwort zweimal ab und zeigt beim Tippen nichts an. Er funktioniert bei gestopptem und bei laufendem Server, und er aktiviert das Konto, falls es inaktiv war. Sie erhalten also nicht ein korrektes Passwort und eine Anmeldung, die trotzdem ablehnt. Mit `--data-dir <Ordner>` geben Sie einen anderen Ort als den Standardordner an. Falls ein Skript das übernehmen muss, gibt es `--password <Passwort>`; ein so übergebenes Passwort ist jedoch in der Prozessliste und im Verlauf der Shell sichtbar, deshalb ist die Abfrage der bessere Standard.

Denselben Befehl gibt es ohne eingerichteten PATH als `python -m openconstructionerp reset-password you@example.com`.

**Sie sehen:** Der letzte Administrator hat das Projekt verlassen oder wurde deaktiviert, und niemand erreicht die **Benutzerverwaltung**.
**Das heißt:** Die Installation hat keinen aktiven Administrator, also kann niemand jemanden freischalten oder befördern.
**Was tun:** Stellen Sie einen von einem Terminal aus wieder her:

```
openconstructionerp promote-admin you@example.com
```

Der Befehl macht dieses Konto zum Administrator und aktiviert es; eine Adresse, die es nicht gibt, lehnt er ab, statt sie anzulegen. Nutzen Sie danach `reset-password`, wenn Sie außerdem ein neues Passwort brauchen.

**Sie sehen:** "Password must be 72 bytes or fewer when encoded as UTF-8" beim Anlegen eines Kontos oder beim Setzen eines neuen Passworts.
**Das heißt:** Das Passwort ist länger, als der Hash fassen kann, in dem es gespeichert wird. Buchstaben außerhalb von ASCII (mit Akzent, kyrillisch, arabisch, chinesisch) belegen zwei oder drei Bytes, deshalb liegt ein Passwort aus 30 solchen Zeichen über der Grenze, obwohl es kurz aussieht.
**Was tun:** Kürzen Sie es. Es wurde nichts gespeichert, Konto und Passwort sind also unverändert. Leerzeichen innerhalb des Passworts sind in Ordnung; Leerzeichen an den beiden Enden gehören hier nicht zum Passwort und werden entfernt, bevor es geprüft und bevor es gespeichert wird. Ein Passwort, das mit einem Leerzeichen am Ende eingefügt wurde, meldet sich deshalb trotzdem an.

## Den Server selbst starten: der erste Start

**Sie sehen:** Der Browser meldet, die Seite sei nicht erreichbar - eine bis zwei Minuten, nachdem Sie den Server gestartet haben.
**Das bedeutet:** Der Port öffnet sich erst, wenn der erste Start seine Arbeit beendet hat: Datenbankschema anlegen, Module laden, Routentabelle aufbauen. Bis dahin hört niemand auf dem Port. Der Browser ist also nicht langsam und der Server lehnt Sie nicht ab - er ist noch nicht an dem Punkt, an dem er überhaupt antworten kann. Ein Start, der alles durchführt, erreicht einen offenen Port nach etwa 143 Sekunden auf einem ruhigen Rechner, und die längste einzelne Phase darin ist die Routentabelle mit 32 Sekunden auf einem ruhigen und 59 Sekunden auf einem ausgelasteten Rechner. In der Testsuite, die bei jedem Commit läuft, dauerte die ganze Folge - starten, auf die Gesundheitsprüfung warten, registrieren, anmelden - 58 Sekunden unter Linux, 59 unter macOS und 106 unter Windows. Ein erster Start mit einem leeren Datenverzeichnis ist der langsamste Start, den Sie je sehen werden; jeder weitere nutzt diese Arbeit wieder und öffnet in Sekunden.
**Tun Sie Folgendes:** Lassen Sie das Terminalfenster offen und lesen Sie es, statt den Browser neu zu laden. Ein gesunder Start gibt pro Phase eine Zeile aus, sobald er sie erreicht, und solange eine Phase dauert, gibt er alle fünfzehn Sekunden `Still working: <Phase> (<Sekunden>s)` aus - ein Fenster, das schreibt, ist also ein Start, der vorankommt. Das Banner mit der Adresse wird ausgegeben, bevor der Server antworten kann - seine eigene Überschrift sagt, die Anwendung *startet*, nicht dass sie läuft, und die Adresse sofort zu öffnen ergibt einen Browserfehler von einer Installation, die völlig korrekt arbeitet. Die Zeilen, die bedeuten, dass er antworten kann, kommen vom Server und nicht vom Starter: `Application startup complete.` und `Uvicorn running on http://127.0.0.1:8080`. Zwei Dinge bedeuten, dass wirklich etwas falsch ist: vier Minuten lang keine neue Zeile - das ist das Intervall, das der Desktop-Starter selbst benutzt, um einen gestoppten Start zu erkennen - und eine Zeile mit `Traceback`. Wenn Sie eines von beiden sehen, legen Sie die letzten zwanzig Zeilen dieses Fensters zusammen mit den Protokolldateien vom Anfang dieser Seite in einen Bericht.

**Sie sehen:** Die Seite öffnet sich und meldet sofort, Daten konnten nicht geladen werden, oder die Anmeldeseite sagt, der Arbeitsbereich werde noch vorbereitet.
**Das bedeutet:** Die Seite hat den Server erreicht, während der Server noch gestartet ist - bei einem ersten Start ist das die normale Reihenfolge und kein Fehler. Die Oberfläche fragt, ob der Server bereit ist, wartet und fragt erneut, in einem Plan, der zurückweicht: drei Sekunden, dann sechs, dann zwölf, dann vierundzwanzig, danach jeweils eine halbe Minute. Nach etwa zweieinhalb Minuten hört sie auf zu fragen, sagt, dass der Server noch startet, und legt einen Button **Erneut versuchen** auf die Seite, denn eine Seite, die still für immer weiterfragt, sieht genauso aus wie eine, die aufgegeben hat. Eine Meldung "Startet noch" ist dasselbe Urteil über eine einzelne Anfrage: Der Server hat 503 geantwortet, und das antwortet er, solange er hochfährt.
**Tun Sie Folgendes:** Drücken Sie **Erneut versuchen**, wenn Sie ihn sehen, oder warten Sie auf `Application startup complete.` im Terminalfenster und laden Sie dann einmal neu. Kommt die Meldung auf jeder Seite zurück, lange nachdem der Start fertig war, ist nicht der Server das, worauf gewartet wird: Führen Sie `openconstructionerp doctor` aus und lesen Sie, was es über den Port und die Datenbank sagt.

**Sie sehen:** Sie haben mit `git pull` eine neuere Version geholt, neu gestartet, und jede Seite sieht genau so aus wie vorher.
**Das bedeutet:** Der Server liefert die Oberfläche nicht aus den Dateien, die Sie geholt haben. Er liefert eine Kopie, die früher gebaut wurde - aus `backend/app/_frontend_dist`, wenn dieser Ordner existiert, sonst aus `frontend/dist` neben dem Paket - und `git pull` holt Quelltext, ohne etwas zu bauen. Ihr Browser legt eine zweite Schicht darüber: Ein Service Worker liefert weiter die Kopie aus seinem Cache, sodass selbst ein neu gebauter Ordner unverändert aussehen kann, bis dieser Cache geleert ist.
**Tun Sie Folgendes:** Bauen Sie die Oberfläche neu und löschen Sie danach die Kopie im Browser. In der Windows PowerShell, vom Repository-Ordner aus:

```
cd frontend
$env:NODE_OPTIONS="--max-old-space-size=8192"
npm ci
npm run build
```

Unter Linux oder macOS dieselben vier Zeilen, mit `export NODE_OPTIONS=--max-old-space-size=8192` anstelle der zweiten. Die Variable hebt den Speicher an, den der Build benutzen darf; ohne sie kann ein Build auf einem Rechner mit 8 GB oder weniger mit `JavaScript heap out of memory` abbrechen. Bricht er trotz gesetzter Variable so ab, führen Sie `npx vite build` statt `npm run build` aus: Das erzeugt dasselbe Bündel und überspringt den separaten Typ-Check, also den Teil, der am meisten Speicher braucht. Öffnen Sie danach im Browser die Entwicklertools (F12), gehen Sie zu **Application**, drücken Sie **Unregister** beim Service Worker, drücken Sie **Clear site data** und laden Sie mit Strg+F5 neu. Um zu sehen, welchen Ordner Ihr Server tatsächlich liest, führen Sie dies vom Ordner `backend` aus:

```
python -c "from app.cli_static import get_frontend_dir; print(get_frontend_dir())"
```

**Sie sehen:** Sie haben sich registriert, und die Anmeldung antwortet mit "Invalid email or password" oder sagt, das Konto sei angelegt und ein Administrator müsse es aktivieren.
**Das bedeutet:** Das Konto existiert und ist noch nicht aktiv. Bei einer Installation, die nicht ganz neu ist, ist das der Standard und kein Fehler; das erste Konto auf einer wirklich leeren Datenbank ist die Ausnahme und wird aktiviert und zum Administrator gemacht, denn eine neue Installation ohne Zugang ist keine Installation.
**Tun Sie Folgendes:** Lesen Sie [Anmelden bei einer Installation, die Sie selbst betreiben](#anmelden-bei-einer-installation-die-sie-selbst-betreiben) oben - dorthin gibt dieser Abschnitt den Fall weiter. Der Abschnitt nennt die drei Wege: die Registrierung mit `OE_REGISTRATION_MODE` öffnen, das Konto als Administrator aktivieren, und ein neues Passwort von einem Terminal aus setzen - mit dem, was jeder der drei kostet, und der Passwortregel, die das Formular vor dem Absenden nennt.

## Deinstallieren und Ihre Daten

Die Deinstallation entfernt das Programm und behält Ihre Projekte. Sie liegen im Ordner `.openestimate` in Ihrem Benutzerordner (dazu der oben genannte `ProgramData`-Ordner, wenn Ihr Benutzername nicht-lateinische Buchstaben enthält). Eine Neuinstallation fängt deshalb nicht von vorn an. Für einen echten Neuanfang deinstallieren Sie und löschen `.openestimate` selbst, nachdem Sie es an einen sicheren Ort kopiert haben.

## Immer noch Probleme?

Eröffnen Sie ein Issue unter [github.com/abdelnabym519-cpu/Construction-AI-OS/issues](https://github.com/abdelnabym519-cpu/Construction-AI-OS/issues). Bitte nennen Sie:

- die installierte Version und den Weg (Windows-Installationsprogramm, `.dmg`, `.deb`, `.rpm`, AppImage, pip oder Docker),
- Ihr System (Windows: Start, `winver` eingeben; macOS: Apple-Menü, Über diesen Mac),
- den genauen Text der Meldung oder einen Screenshot,
- die Protokolldateien vom Anfang dieser Seite.
