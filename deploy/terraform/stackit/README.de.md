# OpenConstructionERP auf STACKIT, eine isolierte Instanz pro Unternehmen

[English](README.md) | Deutsch | [Русский](README.ru.md)

Terraform-Module, die OpenConstructionERP in der deutschen Cloud [STACKIT](https://www.stackit.de)
betreiben, mit einer **eigenen Instanz für jedes Unternehmen**: eigener Datenbankserver, eigener
Bucket, eigene Zugangsdaten und eigener Namespace. Die Daten bleiben in deutschen Rechenzentren
(Region `eu01`).

```
deploy/terraform/stackit/
  modules/platform/   gemeinsame Schicht: SKE-Cluster, ingress-nginx, cert-manager, optional DNS-Zone und Observability
  modules/company/    ein Unternehmen: PostgreSQL Flex, Bucket, Namespace, App, TLS-Ingress, DNS-Eintrag
  examples/two-companies/   Vorlage zum Kopieren: ein Produktiv- und ein Sandbox-Unternehmen
```

## Was pro Unternehmen angelegt wird

| Ressource | Zweck |
|---|---|
| PostgreSQL-Flex-Instanz, Benutzer, Datenbank | Eigener Datenbankserver des Unternehmens. Nur die Egress-Adressen des Clusters dürfen sich verbinden (ACL). Tägliche Backups, 32 bis 90 Tage Aufbewahrung |
| Object-Storage-Bucket, Credentials-Gruppe, Credential | Eigener Bucket und eigene Schlüssel für BIM/CAD-Dateien und Dokumente |
| Kubernetes-Namespace `oce-<slug>` | Isolationsgrenze, mit Unternehmen und Modus gekennzeichnet |
| ResourceQuota und LimitRange | Ein Unternehmen kann Nachbarn keine Ressourcen entziehen |
| NetworkPolicy | Eingehend nur vom Ingress-Controller; ausgehend nur DNS und öffentliches Internet, nie zu anderen Namespaces oder ins Knotennetz |
| Secret `oce-env` | Datenbank-URL, JWT-Secret, S3-Schlüssel, optional SMTP-Passwort und Model-Serving-Token |
| ConfigMap `oce-config` | Alle nicht geheimen Einstellungen |
| PersistentVolumeClaim `oce-data` | Das Verzeichnis `/data` (rund 20 Module schreiben dorthin, auch bei S3-Speicher) |
| Deployment (1 Replika, `Recreate`) | Die Anwendung, auf eine feste Image-Version festgelegt |
| Service und Ingress | Öffentliches HTTPS mit Let's-Encrypt-Zertifikat, Uploads bis 512 MB |
| DNS-A-Eintrag | `<slug>.<base_domain>` auf die Ingress-Adresse (optional) |
| AI-Model-Serving-Token | Optional, für die Roadmap vorbereitet (siehe unten) |

Einmal gemeinsam: der SKE-Cluster, ingress-nginx, cert-manager und eine optionale Observability-Instanz.

## Voraussetzungen

- Ein STACKIT-Projekt und ein **Service-Account-Schlüssel** (JSON) mit Rechten zum Anlegen der obigen Ressourcen.
- **Object Storage aktiviert** im Projekt (einmalig im STACKIT-Portal).
- Eine Domain, die Sie an STACKIT DNS delegieren können, oder eine vorhandene STACKIT-DNS-Zone. Ohne
  DNS-Automatisierung `zone_id = null` setzen und die A-Einträge selbst anlegen.
- Terraform 1.7 oder neuer (CI nutzt 1.9) und Netzzugang zu `ghcr.io`.
- Eine PostgreSQL-Flex-Flavor-ID: `stackit postgresflex flavor list`.

## Schnellstart

```bash
cd deploy/terraform/stackit/examples/two-companies
export STACKIT_SERVICE_ACCOUNT_KEY_PATH=/pfad/zum/key.json
cp terraform.tfvars.example terraform.tfvars        # Projekt, Domain, Flavor, Unternehmen anpassen
terraform init
terraform apply -target=module.platform             # Cluster, Ingress, Zertifikate (nur beim ersten Lauf)
terraform apply                                     # Datenbanken, Buckets und die Unternehmen
```

`terraform output urls` zeigt die Adressen. **Öffnen Sie die URL und registrieren Sie sich: Der
erste registrierte Benutzer wird Administrator** dieser Instanz. Weitere Registrierungen folgen
`registration_mode` (Standard `admin-approve`).

Der erste Start einer Instanz legt rund 600 Tabellen an und dauert einige Minuten; der Startup-Probe
wartet bis zu 15 Minuten.

Verlagern Sie den State vor dem produktiven Einsatz in ein Remote-Backend, siehe
`examples/two-companies/backend.tf.example`. Der State enthält Datenbankpasswörter und
Speicherschlüssel im Klartext, halten Sie ihn daher privat und verschlüsselt. Ein PostgreSQL-Backend
(`pg`) bietet State-Locking; das S3-Backend auf STACKIT Object Storage funktioniert, hat aber kein Locking.

## Unternehmen hinzufügen

Eintrag in der Map `companies` ergänzen und anwenden:

```hcl
companies = {
  acme   = { display_name = "Acme Construction GmbH" }
  bauer  = { display_name = "Bauer Hochbau", custom_hostname = "erp.bauer.example" }
}
```

Das neue Unternehmen erhält eigene Datenbank, eigenen Bucket und eigenen Namespace; bestehende
Unternehmen bleiben unberührt. Bei `custom_hostname` außerhalb Ihrer Zone muss der Kunde den
DNS-Eintrag (A auf die Ingress-Adresse) selbst setzen; setzen Sie dann `create_dns_record = false`.

## Von der Sandbox in die Produktion

Eine Sandbox (`mode = "sandbox"`) hat Demodaten (`SEED_DEMO=true`), kleinere Größen und das Label
`oce/expires=<Datum>` an allen Objekten (Standard 30 Tage, `sandbox_days`). Das Label ist nur eine
Information: **Es wird nichts automatisch gelöscht.** Um aus einer Sandbox ein Produktiv-Unternehmen
zu machen, legen Sie einen neuen Produktiv-Eintrag an; Demodaten werden nicht migriert, Sandboxes
dienen also dem Testen. Legen Sie keine echten Projektdaten in einer Sandbox ab.

## Unternehmen entfernen

1. Eintrag aus der Map löschen. Terraform entfernt Namespace, Datenbank und Bucket.
2. Ein Bucket mit Objekten **kann nicht gelöscht werden**. Leeren Sie ihn zuerst (STACKIT-Portal oder
   ein S3-Werkzeug mit den Schlüsseln des Unternehmens aus `terraform output`) und wenden Sie erneut an.
3. Das Löschen der PostgreSQL-Instanz löscht auch deren Backups. Exportieren Sie vorher, was Sie brauchen.

## Dimensionierung

| | Sandbox | Produktion |
|---|---|---|
| App-Speicher Request / Limit | 1 GiB / 2 GiB | 1 GiB / 3 GiB |
| App-CPU-Request | 500m | 500m |
| Volume `/data` | 10 GB | 50 GB |
| PostgreSQL-Speicher | 10 GB | 50 GB |
| Backup-Aufbewahrung | 32 Tage | 35 Tage |
| Benötigte Knotenkapazität | ca. 0,5 vCPU, 1 GiB | ca. 0,5 vCPU, 1 GiB, Spitze bis 3 GiB |

Alle Werte lassen sich pro Unternehmen überschreiben. Ein Knoten mit 4 vCPU / 8 GiB fasst etwa drei
Unternehmen. Erhöhen Sie `minimum`/`maximum` in `node_pools`, wenn Unternehmen hinzukommen. Wählen Sie
den PostgreSQL-Flavor (`postgres_flavor_id`) nach Unternehmensgröße; beginnen Sie klein, er lässt
sich später ändern.

## Sicherheitshinweise

- **Isolation pro Unternehmen:** eigener Namespace mit NetworkPolicy, eigene PostgreSQL-Instanz
  (eigener Server, nicht nur ein eigenes Schema), eigener Bucket, eigene Zugangsdaten, eigenes JWT-Secret.
- Die Datenbank akzeptiert Verbindungen nur von den Egress-Adressen des Clusters, und die Anwendung
  verbindet sich mit aktiviertem TLS.
- Geheimnisse liegen in Kubernetes-Secrets (base64, von Kubernetes selbst nicht verschlüsselt) und im
  Terraform-State. Verschlüsseln Sie den State im Ruhezustand und beschränken Sie den Zugriff auf
  State und Cluster.
- Beschränken Sie `api_allowed_cidrs` (ACL der Kubernetes-API) auf Büro- oder CI-Adressen.
- Der Container läuft ohne Root-Rechte, alle Capabilities sind entfernt, das seccomp-Profil ist RuntimeDefault.
- Das JWT-Secret wird einmal pro Unternehmen erzeugt und bleibt fest; entfernen Sie es nicht aus dem
  State, sonst enden alle Sitzungen.
- Image-Versionen sind festgelegt (`latest` wird abgelehnt). Ein Upgrade erfolgt über `image_tag` und Apply.

## Warum eine Replika und die Strategie `Recreate`

Beim Start wird das Schema erzeugt, der Auto-Heal-Migrator ausgeführt (durch ein Advisory-Lock der
Datenbank geschützt) und der Migrationsstand ohne Sperre gestempelt. Zwei gleichzeitig startende
Instanzen, wie bei einem Rolling Update, könnten kollidieren. Das Volume `/data` ist außerdem
`ReadWriteOnce` und wird nur an einen Knoten gleichzeitig angehängt. Das Modul betreibt daher genau
eine Replika und ersetzt sie per `Recreate`: erst stoppt der alte Pod, dann startet der neue. Ein
Upgrade bedeutet deshalb eine kurze Downtime (nach dem ersten Start typischerweise unter einer
Minute). Redis und Qdrant werden nicht bereitgestellt: Der Job-Runner fällt auf Ausführung im Prozess
zurück, und das Image bringt einen eingebetteten Vektorspeicher unter `/data/vectors` mit.

## Roadmap, nicht in dieser Version

- OIDC-Single-Sign-On für Unternehmens-Logins.
- AI Model Serving in der App: Das Modul kann ein Token erzeugen und legt `STACKIT_MODEL_SERVING_TOKEN`
  sowie `STACKIT_MODEL_SERVING_BASE_URL` im Unternehmens-Secret ab. Die Anwendung liest noch keine
  OpenAI-kompatible Basis-URL aus der Umgebung (Roadmap-Paket 4).
- Ein Backup-/Export-Befehl für ein ganzes Unternehmen (Datenbank-Dump, Bucket und `/data`).
- Optionaler Migrations-Job vor dem Start (heute migriert sich die Anwendung beim Start selbst).

## Vor dem ersten Apply prüfen

Die Module wurden anhand der Provider-Dokumentation ohne Zugriff auf ein STACKIT-Konto geschrieben.
CI prüft Formatierung, Schema-Gültigkeit und Logik mit gemockten Providern; Folgendes kann sie nicht
bestätigen. Prüfen Sie es beim ersten Lauf (`terraform validate` und `plan` weisen auf das meiste hin):

1. `stackit_postgresflex_instance`: Attributnamen `flavor_id`, `network.acl`, `storage`,
   `retention_days` und der Ausgabepfad `connection_info.write.host` / `.port`.
2. PostgreSQL Flex: zulässige Länge des Instanznamens (Namen sind `oce-<slug>`, bis zu 24 Zeichen),
   minimale Speichergröße, ob der Server TLS verlangt (`?ssl=require` ist standardmäßig gesetzt;
   `database_ssl = false` nur, wenn die Verbindung daran scheitert) und ob Benutzer mit den Rollen
   `login` und `createdb` alle Tabellen anlegen können.
3. Der Query-Parameter `ssl=require` und der Variablenname `DATABASE_SYNC_URL` in Ihrer Image-Version
   (die Einstellungen lesen `database_sync_url`).
4. SKE: Maschinentyp `c1.4` und Zone `eu01-1` existieren in Ihrem Projekt (`node_pools` anpassen),
   `kubernetes_version_min`, und dass der Block der Erweiterung `observability` `instance_id` akzeptiert.
5. SKE-Kubeconfig: Das Modul erwartet Client-Zertifikatsdaten (`client-certificate-data`) in der
   erzeugten Kubeconfig. Liefert STACKIT eine OIDC- bzw. token-basierte Konfiguration, passen Sie
   `providers.tf` an.
6. `egress_address_ranges` ist die Adresse, die die Datenbank tatsächlich sieht. Erreichen Pods die
   Datenbank über einen anderen Weg, erweitern Sie `postgres_allowed_cidrs`.
7. Ein Service vom Typ `LoadBalancer` erhält ohne zusätzliche Annotationen eine öffentliche Adresse
   von STACKIT (erwartet, nicht bestätigt), und Client-IPs erreichen die App über `X-Forwarded-For`
   (`externalTrafficPolicy` ist der Standard `Cluster`, die App sieht daher evtl. Knotenadressen).
8. Der Standard von `TRUSTED_PROXIES` deckt die üblichen Pod- und Knotenbereiche ab (`10.0.0.0/8`,
   `100.64.0.0/10`, ...). Prüfen Sie, dass das Pod-CIDR Ihres Clusters darin liegt.
9. Container-Benutzer-ID: Der Image-Benutzer `oe` ist ein Systembenutzer; `run_as_uid` ist standardmäßig
   999. Prüfen mit `docker run --rm --entrypoint id ghcr.io/datadrivenconstruction/openconstructionerp:<tag>`.
10. Format des DNS-Record-Set-Namens (verwendet wird der vollqualifizierte Name mit Punkt am Ende) und die TTL.
11. Object Storage: Namensregeln und Eindeutigkeit des Buckets (`oce-<slug>-data`), ob das Credential
    keine zusätzliche Berechtigung braucht, und der S3-Endpunkt `https://object.storage.eu01.onstackit.cloud`
    mit Path-Style-Zugriff im S3-Client der Anwendung.
12. AI Model Serving: `stackit_modelserving_token` kann in manchen Provider-Versionen ein
    Experiment-Flag benötigen; das Token wird nur mit `enable_model_serving = true` erzeugt.
13. Festgelegte Chart-Versionen (ingress-nginx 4.11.3, cert-manager v1.15.3) und das
    ingress-nginx-Chart-Repository sind vom Cluster aus erreichbar. Sandbox mit `SEED_DEMO=true` unter
    `APP_ENV=production`: Prüfen Sie, dass Demokonten in Ihrer Image-Version wie erwartet entstehen.
14. Das erste `terraform apply -target=module.platform` ist nötig, weil die Kubernetes- und
    Helm-Provider aus einem Cluster konfiguriert werden, der noch nicht existiert.

## Kosten

Sie zahlen für die SKE-Worker-Knoten, pro Unternehmen eine PostgreSQL-Flex-Instanz und einen Bucket,
den LoadBalancer und optional Observability. Die Plattformschicht wird geteilt; ein weiteres
Unternehmen kostet daher vor allem seine PostgreSQL-Instanz plus einen Bruchteil eines Knotens.
