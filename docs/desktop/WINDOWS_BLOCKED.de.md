# Windows blockiert die App (unbekannter Herausgeber)

Auch auf [English](WINDOWS_BLOCKED.md) und [Русский](WINDOWS_BLOCKED.ru.md).

Diese Seite ist für Sie, wenn Windows OpenConstructionERP nicht starten lässt, die App als Programm eines unbekannten oder nicht verifizierten Herausgebers bezeichnet, oder sie einmal laufen ließ und seitdem bei jedem Start blockiert.

Die Bezeichnungen der Windows-Oberfläche stehen hier so, wie ein deutsches Windows 11 sie zeigt, mit dem englischen Namen in Klammern. Je nach Windows-Version kann der deutsche Wortlaut leicht abweichen.

## Warum das passiert

Die Windows-Builds von OpenConstructionERP sind noch nicht code-signiert. Über die Signatur erfährt Windows, wer ein Programm veröffentlicht hat. Ohne sie gilt die App als Programm eines unbekannten Herausgebers. Darauf reagieren zwei getrennte Windows-Funktionen, und sie brauchen unterschiedliche Schritte:

- **Microsoft Defender SmartScreen** zeigt ein blaues Fenster "Der Computer wurde durch Windows geschützt" (Windows protected your PC), wenn Sie ein aus dem Internet geladenes Programm starten, das Windows noch nicht kennt. SmartScreen warnt und lässt Sie fortfahren.
- **Smart App Control** ist eine strengere Funktion von Windows 11. Wenn sie eingeschaltet ist, blockiert sie jede Programmdatei, für die der Cloud-Dienst von Microsoft nicht bürgen kann und die keine vertrauenswürdige Signatur trägt. Sie bietet keine Schaltfläche zum Fortfahren und keine Ausnahme für einzelne Apps. Ihre Meldung nennt Smart App Control und sagt meist, dass die App oder ein Teil davon blockiert wurde.

Smart App Control erklärt auch den verwirrendsten Fall, in dem die App einmal lief und danach bei jedem Start blockiert wird. Nach einer Neuinstallation von Windows startet Smart App Control in einem Bewertungsmodus (Evaluation), in dem es nur beobachtet und nichts blockiert. Später entscheidet Windows, ob es die Funktion dauerhaft ein- oder ausschaltet. Schaltet es sie ein, wird ein Programm, das gestern lief, heute blockiert, obwohl sich auf unserer Seite nichts geändert hat. Außerdem entpackt die Desktop-App bei jedem Start einige hundert Hilfsdateien, darunter die eingebettete PostgreSQL-Datenbank, und Smart App Control prüft jede davon, nicht nur die heruntergeladene Datei.

Der Name in der Benachrichtigung kann irreführen. Die Sperre kommt aus der App Windows-Sicherheit, egal wie das Popup aussieht. Der nächste Schritt ist deshalb herauszufinden, welche Funktion blockiert hat.

## Schritt 1: herausfinden, was blockiert hat

1. Öffnen Sie **Start**, geben Sie **Windows-Sicherheit** ein und öffnen Sie die App.
2. Gehen Sie zu **Viren- & Bedrohungsschutz** (Virus & threat protection) und dann zu **Schutzverlauf** (Protection history).
3. Sehen Sie sich die neuesten Einträge an. Ein Eintrag, der **Smart App Control** oder eine **blockierte App** nennt, stammt von Smart App Control. Ein Eintrag über eine erkannte Bedrohung stammt von Microsoft Defender Antivirus.

Prüfen Sie dann, ob Smart App Control eingeschaltet ist: In Windows-Sicherheit unter **App- & Browsersteuerung** (App & browser control) die **Smart App Control-Einstellungen** öffnen. Dort steht **Ein**, **Bewertung** oder **Aus**.

## Schritt 2a: SmartScreen ("Der Computer wurde durch Windows geschützt")

Diese Warnung dürfen Sie gefahrlos übergehen, sobald Sie sicher sind, dass die Datei von uns stammt (siehe "Prüfen, ob der Download echt ist" weiter unten).

1. Klicken Sie im Fenster auf **Weitere Informationen** (More info).
2. Prüfen Sie den Dateinamen und klicken Sie auf **Trotzdem ausführen** (Run anyway).

SmartScreen fragt nur bei Dateien, die aus dem Internet geladen wurden. Fragt es bei demselben Installer immer wieder, können Sie außerdem mit der rechten Maustaste auf die heruntergeladene `.exe` klicken, **Eigenschaften** wählen, unten auf der Registerkarte **Allgemein** das Kästchen **Zulassen** (Unblock) ankreuzen und mit **OK** bestätigen. Das entfernt die Markierung "aus dem Internet geladen" von dieser einen Datei. Auf Smart App Control hat das keinen Einfluss, denn Smart App Control prüft jede Programmdatei, egal woher sie kommt.

## Schritt 2b: Smart App Control ist eingeschaltet

Solange Smart App Control eingeschaltet ist, lässt sich keine einzelne App freigeben. Microsoft selbst rät, die Funktion auszuschalten oder den Herausgeber um eine Signatur zu bitten, und an der Signatur arbeiten wir. Bis dahin haben Sie zwei ehrliche Möglichkeiten.

**Möglichkeit 1: Smart App Control eingeschaltet lassen und die App anders starten.** Das empfehlen wir, wenn Sie den Schutz behalten möchten. Docker und WSL führen OpenConstructionERP in einer kleinen Linux-Umgebung aus, und Linux-Programme prüft Smart App Control nicht. Beide Wege sind unten beschrieben.

**Möglichkeit 2: Smart App Control ausschalten.** Das senkt den Schutz Ihres ganzen PCs, nicht nur für unsere App. Tun Sie es nur, wenn Sie damit einverstanden sind. Auf aktuellen Builds von Windows 11 können Sie Smart App Control später auf derselben Seite wieder einschalten, auf älteren Builds ist das Ausschalten dagegen endgültig, bis Windows zurückgesetzt oder neu installiert wird. Bietet die Seite nach dem Ausschalten keinen Weg zurück, haben Sie einen solchen Build.

1. Öffnen Sie **Windows-Sicherheit**, dann **App- & Browsersteuerung** und die **Smart App Control-Einstellungen**.
2. Wählen Sie **Aus** und bestätigen Sie.
3. Starten Sie OpenConstructionERP erneut.

Microsoft Defender Antivirus und SmartScreen bleiben in jedem Fall aktiv.

Zeigt der Schutzverlauf stattdessen eine Erkennung durch Microsoft Defender Antivirus, und Sie haben die Datei wie unten beschrieben geprüft, können Sie den Eintrag öffnen und **Aktionen** (Actions), dann **Auf Gerät zulassen** (Allow on device) wählen. Wenn Sie unsicher sind, lassen Sie es und schreiben Sie uns.

## Mit Docker starten (funktioniert mit eingeschalteter Smart App Control)

1. Installieren Sie **Docker Desktop** von docker.com und starten Sie es einmal. Docker Desktop ist kostenlos für private Nutzung, Bildung und kleine Unternehmen; größere Unternehmen brauchen ein kostenpflichtiges Docker-Abonnement.
2. Legen Sie einen Ordner an, zum Beispiel `C:\OpenConstructionERP`, öffnen Sie darin **Windows PowerShell** und führen Sie aus:

```powershell
curl.exe -fsSL https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionERP/main/docker-compose.quickstart.yml -o docker-compose.yml
curl.exe -fsSL https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionERP/main/docker-compose.quickstart.image.yml -o docker-compose.override.yml
function New-Secret([int]$n) { $b = New-Object byte[] $n; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString("x2") }) }
Set-Content -Path .env -Encoding ascii -Value @("POSTGRES_PASSWORD=$(New-Secret 24)", "JWT_SECRET=$(New-Secret 32)")
docker compose pull app
docker compose up -d
```

3. Öffnen Sie **http://localhost:8080** im Browser und melden Sie sich mit `demo@openconstructionerp.com` / `DemoPass1234!` an.

Die Datei `.env` enthält das Datenbank-Passwort und das Anmelde-Geheimnis, bewahren Sie sie auf. Beim nächsten Mal genügt `docker compose up -d` im selben Ordner.

## In WSL starten (funktioniert mit eingeschalteter Smart App Control)

WSL ist die in Windows eingebaute Linux-Umgebung von Microsoft.

1. Öffnen Sie **Windows PowerShell als Administrator**, führen Sie `wsl --install` aus und starten Sie den PC neu, wenn Sie dazu aufgefordert werden. Beim ersten Start fragt Ubuntu nach einem Benutzernamen und Passwort.
2. Führen Sie im **Ubuntu**-Fenster aus:

```bash
sudo apt update && sudo apt install -y python3-venv
python3 -m venv ~/openconstructionerp
~/openconstructionerp/bin/pip install --upgrade openconstructionerp
~/openconstructionerp/bin/openconstructionerp
```

3. Öffnen Sie **http://localhost:8080** im Windows-Browser. Der erste Start dauert ein bis zwei Minuten, während die Datenbank eingerichtet wird. Beim nächsten Mal Ubuntu öffnen und nur die letzte Zeile ausführen.

## Mit pip unter Windows starten (nur mit ausgeschalteter Smart App Control)

Ist Smart App Control ausgeschaltet oder nie eingeschaltet worden, und Sie möchten den Installer nicht verwenden, können Sie die App direkt mit Python starten. Verlassen Sie sich nicht auf diesen Weg, um Smart App Control zu umgehen: Die App startet ihre eigene PostgreSQL-Datenbank, deren Programmdateien ebenfalls nicht signiert sind. Mit eingeschalteter Smart App Control wird die Datenbank genauso blockiert.

1. Laden Sie Python 3.12 von [python.org/downloads/windows](https://www.python.org/downloads/windows/) und starten Sie den Installer. Kreuzen Sie auf der ersten Seite **Add python.exe to PATH** an und klicken Sie auf **Install Now**.
2. Öffnen Sie ein neues **Windows PowerShell**-Fenster und führen Sie aus:

```powershell
py -3.12 -m pip install --upgrade openconstructionerp
py -3.12 -m openconstructionerp
```

3. Der erste Start richtet die lokale Datenbank ein und lädt Demodaten, das dauert etwa eine Minute. Danach läuft die App unter **http://localhost:8080**; Anmeldung mit `demo@openconstructionerp.com` / `DemoPass1234!`. Beim nächsten Mal genügt der zweite Befehl.

## Prüfen, ob der Download echt ist

Jedes Release enthält neben den Installern eine Datei `SHA256SUMS`. Laden Sie sie in denselben Ordner wie den Installer, öffnen Sie dort **Windows PowerShell** und führen Sie aus:

```powershell
$exe = Get-ChildItem OpenConstructionERP_*_x64-setup.exe | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$line = Select-String -Path SHA256SUMS -Pattern $exe.Name -SimpleMatch
(Get-FileHash $exe.FullName -Algorithm SHA256).Hash -eq $line.Line.Split(' ')[0]
```

`True` bedeutet, dass die Datei genau die ist, die unser Release-Build erzeugt hat. `False` bedeutet, dass sie unterwegs beschädigt oder verändert wurde. Starten Sie sie dann nicht. Eine rote Fehlermeldung statt `True` oder `False` bedeutet, dass im Ordner eine `SHA256SUMS` aus einem anderen Release als der Installer liegt; laden Sie dann beide von derselben Release-Seite. Bleibt es bei `False`, laden Sie die Datei erneut von der [GitHub-Release-Seite](https://github.com/datadrivenconstruction/OpenConstructionERP/releases/latest). Die Prüfung belegt, dass die Datei unverändert ist. An der Entscheidung von SmartScreen oder Smart App Control ändert sie nichts. Für eine stärkere Prüfung trägt `SHA256SUMS` selbst eine Sigstore-Signatur, beschrieben in [RELEASE_SIGNATURE_INVENTORY.md](RELEASE_SIGNATURE_INVENTORY.md).

## Es klappt immer noch nicht

Schreiben Sie an info@datadrivenconstruction.io oder eröffnen Sie ein Issue auf GitHub. Nennen Sie Ihre Windows-Version (Start, `winver` eingeben), was die Seite Smart App Control-Einstellungen anzeigt, und den genauen Text der Meldung.

## Quellen

- Microsoft Learn, [SmartScreen reputation for Windows app developers](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
- Microsoft Learn, [Smart App Control overview](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview)
- Microsoft Support, [Häufig gestellte Fragen zu Smart App Control](https://support.microsoft.com/de-de/windows/smart-app-control-frequently-asked-questions-285ea03d-fa88-4d56-882e-6698afdb7003)
- Microsoft Support, [Smart App Control hat einen Teil dieser App blockiert](https://support.microsoft.com/de-de/windows/security/threat-malware-protection/smart-app-control-has-blocked-part-of-this-app)
- Microsoft Support, [App- & Browsersteuerung in der App Windows-Sicherheit](https://support.microsoft.com/de-de/windows/security/windows-security/app-browser-control-in-the-windows-security-app)
