# OpenConstructionERP auf Microsoft Azure

[English](azure.md) | Deutsch | [Русский](azure.ru.md)

So betreiben Sie OpenConstructionERP auf Azure, mit Daten in der Region Ihrer Wahl, und was für die Anmeldung mit Microsoft Entra ID heute funktioniert. Es gibt keinen Azure-spezifischen Code: Die Plattform läuft als ein Docker-Container gegen PostgreSQL, alles Folgende ist Konfiguration.

**Was geprüft wurde.** Alle unten genannten Einstellungen wurden gegen den Quellcode der Version 18.8.2 geprüft (`backend/app/config.py`, `backend/app/modules/users/`, `deploy/docker/`). Die Schritte im Azure-Portal und in der CLI stammen aus der Azure-Dokumentation und wurden **nicht** auf einem echten Abonnement ausgeführt. Betrachten Sie die erste Installation als Test und lesen Sie "Anmeldung mit Entra ID", bevor Sie Single Sign-on zusagen.

## Variante wählen

| | Azure-VM mit Docker (empfohlen) | Azure Container Apps |
|---|---|---|
| Aufwand | Eine VM, eine Compose-Datei | Keine VM zu patchen, mehr Teile |
| Dateien in `/data` | Managed Disk, Bind-Mount | Azure-Files-Freigabe (Netzwerkdateisystem) |
| TLS | Reverse Proxy auf der VM (unten) | Im Ingress enthalten |
| Eignung | Die meisten Firmen | Wenn die Richtlinie keine VMs erlaubt |

Beide nutzen **Azure Database for PostgreSQL Flexible Server** (PostgreSQL 16) und betreiben **genau ein Replikat** der Anwendung. Beim Start werden rund 600 Tabellen angelegt und Migrationen ausgeführt; zwei gleichzeitig startende Instanzen können kollidieren. Nicht horizontal skalieren.

Das veröffentlichte Image ist für `linux/amd64` gebaut. Wählen Sie x64-Größen, keine Arm-Größen.

## Dimensionierung

Der Kern braucht **3 GB Arbeitsspeicher auf einer dedizierten Maschine**: etwa 800 MB für die Anwendung, 200 bis 400 MB für PostgreSQL, wenn es daneben läuft, und eine einmalige Spitze von etwa 1,2 GB beim Import eines Länder-Kostenpakets (ab Version 17.7.0). Die Herleitung steht in [INSTALL_LINUX.md](../INSTALL_LINUX.md#what-the-machine-needs). Mit der Datenbank auf dem Flexible Server trägt die VM kein PostgreSQL mehr, der Puffer für den Import bleibt trotzdem nötig.

| Teil | Startwert | Hinweise |
|---|---|---|
| VM | 2 vCPU, 8 GiB (z. B. `Standard_D2s_v5`) | Keine Burstable-Größe: Der Speicher gehört Ihnen beim Import nur dem Namen nach. 2 GB Swap ergänzen, falls das Image keinen hat |
| Container Apps | 2 vCPU, 4 GiB, Min. und Max. Replikate 1 | Nicht unter 3 GiB |
| PostgreSQL Flexible Server | Burstable `Standard_B2s` zum Start, General Purpose `Standard_D2ds_v5` für ein ausgelastetes Team, 64 GiB Speicher | Größe später änderbar; Speicher kann nur wachsen |
| Datendisk (`/data`) | 64 GiB Premium SSD | Vektorspeicher und hochgeladene Dateien; rund 20 Module schreiben hierhin |

## Region und Datenresidenz

Legen Sie Ressourcengruppe, VM, Datenbank und Disk in **einer** Region an (etwa `germanywestcentral`, `uaenorth`, `qatarcentral`, `centralindia`). Die Residenz entscheidet sich an diesen Punkten:

- Geo-redundantes Backup nicht aktivieren, solange die gepaarte Region für Sie nicht zulässig ist; dort liegen dann Kopien.
- Aus demselben Grund keine regionsübergreifende Wiederherstellung in Azure Backup für die VM aktivieren.
- Die Anwendung greift nur für Funktionen, die Sie einschalten, ins Internet aus (KI-Anbieter, Karten, Converter-Downloads). Siehe [maps.md](../maps.md) und die KI-Einstellungen, falls ausgehender Verkehr begrenzt werden muss.

## 1. Netzwerk und Datenbank

```bash
az group create -n rg-oce -l germanywestcentral
az network vnet create -g rg-oce -n vnet-oce --address-prefixes 10.20.0.0/16 \
  --subnet-name snet-vm --subnet-prefixes 10.20.1.0/24
```

Legen Sie den PostgreSQL-Server mit privatem Zugriff in einem eigenen delegierten Subnetz an, damit er keine öffentliche Adresse hat (aktuelle Parameter mit `az postgres flexible-server create --help` prüfen):

```bash
az postgres flexible-server create -g rg-oce -n oce-pg-<eindeutig> -l germanywestcentral \
  --version 16 --tier Burstable --sku-name Standard_B2s --storage-size 64 \
  --admin-user oceadmin --admin-password '<langes zufälliges Passwort>' \
  --vnet vnet-oce --subnet snet-pg --address-prefixes 10.20.2.0/24 \
  --backup-retention 14 --geo-redundant-backup Disabled
```

Danach von der VM aus (oder Cloud Shell im selben Netz) Rolle und Datenbank anlegen. Die Anwendung erzeugt ihre Tabellen selbst, daher muss die Rolle Eigentümerin der Datenbank sein:

```sql
CREATE ROLE oe LOGIN PASSWORD '<weiteres langes zufälliges Passwort>';
GRANT oe TO oceadmin;
CREATE DATABASE openestimate OWNER oe;
```

Der Flexible Server verlangt standardmäßig TLS, daher tragen die Verbindungsadressen unten `ssl=require`. Enthält das Passwort `@`, `/` oder `:`, kodieren Sie es in der URL prozentual (`@` wird zu `%40`). Die `OE_DB_*`-Teile des Quickstarts können kein `ssl` setzen, nutzen Sie hier die beiden URLs.

## 2. Die VM

Erstellen Sie eine Ubuntu-24.04-LTS-VM in `snet-vm`, fügen Sie eine Managed Data Disk hinzu und erlauben Sie in der Netzwerksicherheitsgruppe eingehend 80 und 443 (SSH nur von Ihren Büroadressen). Installieren Sie Docker (https://docs.docker.com/engine/install/ubuntu/), formatieren Sie die Datendisk und binden Sie sie unter `/srv/oce-data` ein.

Der Container läuft als Nicht-Root-Benutzer `oe`. Ermitteln Sie dessen numerische ID und übergeben Sie ihm den Ordner:

```bash
docker run --rm --entrypoint id ghcr.io/datadrivenconstruction/openconstructionerp:<version>
sudo chown -R <uid>:<gid> /srv/oce-data
```

Legen Sie `/srv/oce/.env` an (Modus 600). Erzeugen Sie das Geheimnis einmal mit `openssl rand -hex 32` und ändern Sie es nie wieder; sonst enden alle Sitzungen.

```bash
APP_ENV=production
JWT_SECRET=<64 Hex-Zeichen>
DATABASE_URL=postgresql+asyncpg://oe:<passwort>@oce-pg-<eindeutig>.postgres.database.azure.com:5432/openestimate?ssl=require
DATABASE_SYNC_URL=postgresql://oe:<passwort>@oce-pg-<eindeutig>.postgres.database.azure.com:5432/openestimate?sslmode=require
ALLOWED_ORIGINS=https://erp.example.com
REGISTRATION_MODE=admin-approve
```

Mit `APP_ENV=production` verweigert der Server den Start bei einem kurzen oder bekannten `JWT_SECRET` (unter 32 Zeichen). `ALLOWED_ORIGINS` muss exakt die Adresse enthalten, die Nutzer eintippen; ist sie falsch, bleibt die Seite leer und das Serverprotokoll sauber. `TRUSTED_PROXIES` deckt das Docker-Netz bereits ab, der Proxy unten braucht keine Änderung. Redis ist nicht nötig: Ohne Redis laufen Jobs im Prozess der Anwendung.

`/srv/oce/docker-compose.yml`:

```yaml
services:
  app:
    image: ghcr.io/datadrivenconstruction/openconstructionerp:<version>   # veröffentlichte Version festlegen
    restart: unless-stopped
    env_file: .env
    volumes:
      - /srv/oce-data:/data
    expose: ["8080"]
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
volumes:
  caddy_data:
```

`/srv/oce/Caddyfile` (zuerst den DNS-A-Eintrag von `erp.example.com` auf die VM zeigen lassen; das Zertifikat wird automatisch angefordert):

```
erp.example.com {
    reverse_proxy app:8080
}
```

```bash
cd /srv/oce && docker compose up -d
docker compose logs -f app        # der erste Start dauert einige Minuten
```

Öffnen Sie `https://erp.example.com`. **Wer sich zuerst registriert, wird Administrator**; registrieren Sie sich also sofort selbst. Spätere Registrierungen folgen `REGISTRATION_MODE`. Jeder andere Proxy (Application Gateway, Front Door) muss WebSockets, große Uploads und den ursprünglichen Hostnamen erhalten; siehe [deploy/docker/README.md](../../deploy/docker/README.md).

## Alternative: Container Apps

Legen Sie die Umgebung in derselben Region und im selben VNet an, dazu eine Azure-Files-Freigabe für `/data` und eine App mit:

- Image `ghcr.io/datadrivenconstruction/openconstructionerp:<version>`, Zielport **8080**, externer Ingress;
- CPU 2, Speicher 4 Gi, **Min. und Max. Replikate 1**;
- die Freigabe unter `/data` eingebunden;
- die Variablen der obigen `.env`, wobei `JWT_SECRET` und die beiden Datenbank-URLs als Container-Apps-Secrets abgelegt werden.

Ihre Domain fügen Sie unter Custom domains für ein verwaltetes Zertifikat hinzu. Bei öffentlichem Datenbankzugriff die ausgehende Adresse der App am PostgreSQL-Server freigeben. Das Verhalten der Anwendung auf einer SMB-Freigabe wurde nicht getestet; bei Sperrfehlern oder Langsamkeit in `/data` nehmen Sie die VM-Variante.

## Dateien und Objektspeicher

Lassen Sie `STORAGE_BACKEND` auf dem Standard (`local`): Dateien liegen in `/data` auf der Managed Disk. Das Backend `s3` spricht das S3-Protokoll (`S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`), Azure Blob Storage nicht; es lässt sich also nicht direkt anbinden. Ein S3-kompatibler Dienst, den Sie selbst betreiben, geht.

## Anmeldung mit Entra ID

So funktioniert die Anmeldung in 18.8.2: Setzen Sie `OIDC_ENABLED`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID` und `OIDC_CLIENT_SECRET` (optional: `OIDC_SCOPES`, Standard `openid email profile`; `OIDC_AUTO_CREATE_USERS`, Standard true; `OIDC_GROUP_ROLE_MAP`). Die Anmeldeseite zeigt dann "Sign in with SSO". Der Browser wechselt zum Anbieter und kehrt zu `https://<Ihr Host>/auth/oidc/callback` zurück. Der Server tauscht den Code, liest die Benutzerinfo des Anbieters (`sub`, `email`, `name`, `groups`) und stellt eigene Token aus.

**Die direkte Anmeldung gegen Entra ID funktioniert noch nicht.** Zwei Dinge im Code stehen im Weg:

1. Die Anmeldeseite bildet die Autorisierungsadresse als `<issuer>/protocol/openid-connect/auth`. Das ist der Pfad von Keycloak. Entra ID nutzt `https://login.microsoftonline.com/<tenant>/oauth2/v2.0/authorize`.
2. Rollen werden aus einem `groups`-Claim der Benutzerinfo gelesen. Der Entra-Endpunkt liefert keine Gruppen, daher kann `OIDC_GROUP_ROLE_MAP` nicht direkt aus Entra gespeist werden.

Der Server prüft außerdem das ID-Token nicht; er verlässt sich auf die über TLS geholte Benutzerinfo. Beschränken Sie, wer sich anmelden darf, in Entra selbst (Schritt 4).

**Was heute funktioniert: Keycloak als Vermittler.** Betreiben Sie Keycloak (eigener Container oder VM, hier nicht behandelt), binden Sie Entra ID dort als Identity Provider ein und richten Sie die Plattform auf den Keycloak-Realm. Die Plattform sieht ein normales Keycloak, Entra übernimmt Passwörter und Multi-Faktor-Abfragen, und der Gruppen-Mapper von Keycloak liefert den `groups`-Claim.

1. **App-Registrierung in Entra ID** (Microsoft Entra Admin Center, App-Registrierungen, Neue Registrierung): Name `OpenConstructionERP`, Kontotyp "nur dieses Organisationsverzeichnis", Umleitungs-URI vom Typ **Web**: `https://<Keycloak-Host>/realms/<realm>/broker/<alias>/endpoint`. Notieren Sie **Anwendungs-ID (Client)** und **Verzeichnis-ID (Mandant)**.
2. Zertifikate und Geheimnisse, Neuer geheimer Clientschlüssel. Kopieren Sie den **Wert** sofort (er wird nur einmal angezeigt) und notieren Sie das Ablaufdatum; mit Ablauf endet die Anmeldung.
3. API-Berechtigungen: `openid`, `email`, `profile` (delegiert, Microsoft Graph). Unter Tokenkonfiguration den optionalen Claim `email` hinzufügen, und einen Gruppen-Claim, wenn Rollen aus Gruppen kommen sollen.
4. Unternehmensanwendungen, Ihre App, Eigenschaften: "Zuweisung erforderlich" auf Ja und die erlaubten Personen oder Gruppen zuweisen. Ohne das kann sich jeder Benutzer Ihres Mandanten anmelden.
5. **Keycloak:** Identity Providers, "OpenID Connect v1.0" hinzufügen mit dem Discovery-Endpunkt `https://login.microsoftonline.com/<Mandanten-ID>/v2.0/.well-known/openid-configuration` sowie Client-ID und Geheimnis aus Schritt 1 und 2. Legen Sie im Realm einen Client `openconstructionerp` mit der gültigen Umleitungs-URI `https://erp.example.com/auth/oidc/callback` an, dazu einen Client-Scope mit Gruppenmitgliedschafts-Mapper (Claim-Name `groups`, in der Benutzerinfo enthalten).
6. **Plattform:** in `.env` ergänzen und neu starten.

```bash
OIDC_ENABLED=true
OIDC_ISSUER_URL=https://<Keycloak-Host>/realms/<realm>
OIDC_CLIENT_ID=openconstructionerp
OIDC_CLIENT_SECRET=<Keycloak-Client-Geheimnis>
OIDC_GROUP_ROLE_MAP={"oce-admins":"admin","oce-estimators":"editor","oce-viewers":"viewer"}
```

Die zugeordnete Rolle gilt bei jeder Anmeldung; die erste passende Gruppe gewinnt. Wer ohne zugeordnete Gruppe kommt, wird als `editor` angelegt (nicht mit dem Standard `viewer` der Selbstregistrierung); lassen Sie daher "Zuweisung erforderlich" eingeschaltet. Ein vorhandenes lokales Konto mit gleicher E-Mail-Adresse wird bei der ersten SSO-Anmeldung mit der Identität verknüpft.

**Bekannte Probleme in 18.8.2, die jeden Anbieter betreffen** (bei der Prüfung dieser Anleitung gefunden, im Code zu beheben): Ein bereits verknüpfter Benutzer, der sich mit unveränderter Rolle erneut anmeldet, erhält "403 No matching account found"; und mit `OIDC_AUTO_CREATE_USERS=false` erhält ein unbekannter Benutzer einen Serverfehler statt einer sauberen Ablehnung. Testen Sie bis zur Korrektur vor dem Rollout eine zweite Anmeldung derselben Person und steuern Sie den Zugang über "Zuweisung erforderlich" statt über `OIDC_AUTO_CREATE_USERS`.

## Datensicherung

- **Datenbank:** Der Flexible Server erstellt automatische Backups und erlaubt Wiederherstellung zu einem Zeitpunkt innerhalb der Aufbewahrung (7 bis 35 Tage, mit `--backup-retention`). Testen Sie einmal die Wiederherstellung in einen neuen Server; sie überschreibt nie das Original.
- **`/data`:** Snapshot der Managed Disk nach Zeitplan (Azure Backup für die VM oder `az snapshot create`). Datenbank und Disk auf denselben Zeitpunkt zurücksetzen.
- **Eine Kopie unter eigener Kontrolle:** ein nächtliches `pg_dump -Fc` in einen Storage-Container derselben Region. Dass es weiterläuft, prüfen Sie mit [backup-monitoring.md](../backup-monitoring.md).
- Bewahren Sie `.env` und `JWT_SECRET` im Passwortsafe auf; sie sind nicht in den Backups.

## Update

1. Wiederherstellungspunkt der Datenbank (oder `pg_dump`) und Disk-Snapshot erstellen.
2. Release-Hinweise der neuen Version lesen.
3. `<version>` in `docker-compose.yml` ändern, dann `docker compose pull app && docker compose up -d app`.
4. Die Anwendung migriert ihr Schema beim Start selbst; rechnen Sie mit kurzer Downtime. Prüfen Sie `https://erp.example.com/api/health`.
5. Zurück geht es nur mit dem Backup von vor dem Update zusammen mit dem alten Image. Starten Sie nie ein älteres Image auf einer bereits migrierten Datenbank.

## Probleme

| Symptom | Ursache |
|---|---|
| Leere Seite, sauberes Serverprotokoll | `ALLOWED_ORIGINS` passt nicht zur Adresse im Browser |
| Upload scheitert mit 413 | Ein vorgeschalteter Proxy begrenzt die Größe; Caddy hat standardmäßig kein Limit |
| Server stoppt beim Kostenpaket-Import, nichts im Protokoll | Speichermangel, siehe Dimensionierung |
| Keine Verbindung zur Datenbank | Server verlangt TLS (`ssl=require`), VM liegt außerhalb des VNet oder Passwort nicht prozentkodiert |
| Container startet nicht und nennt `JWT_SECRET` | Kürzer als 32 Zeichen bei `APP_ENV=production` |

Weiteres: [INSTALL_LINUX.md](../INSTALL_LINUX.md), [deploy/docker/README.md](../../deploy/docker/README.md), und für Kubernetes mit einer Instanz je Firma [deploy/terraform/stackit](../../deploy/terraform/stackit/README.de.md).
