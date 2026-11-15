# Single Sign-on: OIDC und SAML

Die Anmeldung erfolgt über den Identitätsanbieter (IdP) des Unternehmens statt über ein lokales Passwort. Ein Modul, `oe_sso`, deckt beide Protokolle ab. Ein Admin richtet je Mandant einen oder mehrere Anbieter unter **Einstellungen > Single Sign-on** ein; die Anmeldeseite zeigt für jeden aktiven Anbieter eine Schaltfläche. Umgebungsvariablen sind dafür nicht nötig.

|  | OIDC | SAML 2.0 |
|---|---|---|
| Zusatzpaket | keines | `pip install "openconstructionerp[saml]"` |
| Rücksprungadresse auf Ihrem Host | `/auth/oidc/callback` | ACS-URL auf der Anbieterkarte |
| Gruppen aus | Claim `group_attribute` (Standard `groups`) | Attribut `group_attribute` (Standard `groups`) |

Client-Secrets und das IdP-Zertifikat liegen in der Datenbank, Secrets verschlüsselt. Ein gespeichertes Secret wird nie wieder angezeigt; lassen Sie das Feld leer, um es zu behalten.

## Anbieter hinzufügen

1. Als Admin anmelden und **Einstellungen > Single Sign-on** öffnen.
2. **OpenID Connect hinzufügen** oder **SAML 2.0 hinzufügen** wählen. SAML erscheint nur, wenn das optionale Zusatzpaket installiert ist (siehe unten).
3. Felder ausfüllen, speichern und die Rücksprungadresse im IdP eintragen.

Felder für beide Protokolle:

| Feld | Bedeutung |
|---|---|
| `display_name` (Beschriftung) | Text der Anmeldeschaltfläche |
| `slug` (Kurzname) | Teil der URLs, nach dem Anlegen fest |
| `email_domains` | Nur diese E-Mail-Domänen dürfen sich über diesen Anbieter anmelden; leer heißt jede |
| `tenant_id` | Optionaler Mandant des Anbieters |
| `group_attribute` | Claim oder Attribut mit Gruppen oder Rollen (Standard `groups`) |
| `group_role_map` | Gruppenname (oder Entra-Gruppenobjekt-ID, oder App-Rollenwert) auf Rolle, je Zeile `gruppe=rolle` |
| `default_role` | Rolle für neue Personen ohne zugeordnete Gruppe (Standard `viewer`) |
| `auto_create_users` | Konto bei der ersten Anmeldung anlegen (Standard an) |
| `allow_admin_mapping` | Eine Gruppe darf `admin` vergeben (Standard aus, sonst wird die Zuordnung abgelehnt) |
| `link_by_email` | Anmeldung mit einem lokalen Konto gleicher E-Mail verknüpfen (Standard aus) |
| `clock_skew_seconds` | Erlaubte Zeitabweichung (Standard 120) |
| `enabled` | Schaltfläche auf der Anmeldeseite zeigen |

## OIDC

Zusätzliche Felder: `oidc_issuer` (Issuer-URL), `oidc_client_id`, `oidc_client_secret`, `oidc_scopes` (Standard `openid email profile`). Im IdP die Redirect-URI `https://<ihr-host>/auth/oidc/callback` eintragen. Schritt für Schritt für Microsoft Entra ID: siehe [install/azure.de.md](install/azure.de.md).

Installationen, die bisher die `OIDC_*`-Umgebungseinstellungen nutzten, müssen nichts tun: Beim ersten Start macht die Datenreparatur `sso_env_oidc_provider` daraus einmalig einen Anbietereintrag (Slug `oidc`, gleiche Redirect-URI). Danach werden die Umgebungswerte ignoriert; ändern oder löschen Sie den Eintrag in den Einstellungen.

## SAML 2.0

1. Zusatzpaket auf dem Server installieren: `pip install "openconstructionerp[saml]"` (es bringt `signxml` mit, reines Python, keine Systembibliotheken) und neu starten. Ohne das Paket ist die SAML-Option in den Einstellungen ausgeblendet; OIDC funktioniert weiter.
2. SAML-Anbieter anlegen mit `saml_idp_entity_id`, `saml_idp_sso_url` (HTTP-Redirect-Binding), `saml_idp_cert` (Signaturzertifikat des IdP, PEM) und optional `saml_sp_entity_id`, `saml_email_attribute` (Standard `email`) und `saml_name_attribute` (Standard `displayName`).
3. Die Anbieterkarte zeigt die **ACS-URL** (`https://<ihr-host>/api/v1/sso/saml/<slug>/acs/`, HTTP-POST-Binding), die Entity-ID und die **Metadaten-URL** (`https://<ihr-host>/api/v1/sso/saml/<slug>/metadata/`). Geben Sie dem IdP die Metadaten-URL oder tragen Sie ACS-URL und Entity-ID von Hand ein.

Standardmäßig startet die Anmeldung bei der Anwendung (SP-initiiert): Jede Antwort ist an die Anfrage gebunden, die im selben Browser begann, und lässt sich nur einmal verwenden. Eine wiederholte Antwort wird abgewiesen. IdP-initiierte Anmeldung funktioniert nur, wenn die Anbieteroption `saml_allow_idp_initiated` aktiv ist.

## Wie Personen zugeordnet werden

Eine Person wird über das Paar (Issuer, Subject) des Anbieters erkannt, nicht über die E-Mail. Bei der ersten Anmeldung gilt:

- Ist `link_by_email` aus, wird ein neues Konto angelegt (wenn `auto_create_users` an ist); ein lokales Konto mit gleicher E-Mail bleibt unberührt.
- Ist `link_by_email` an, wird ein vorhandenes lokales Konto mit dieser E-Mail verknüpft. Bei OIDC muss der Anbieter `email_verified` melden.
- Ein Konto, das schon an einen anderen IdP gebunden ist, wird nie umgehängt; die Anmeldung scheitert mit `account_link_refused`.

## Gruppen auf Rollen abbilden

`group_role_map` ordnet Gruppen Rollen zu, zum Beispiel `kalkulation=editor`, `bauleitung=manager`, `finanzen=viewer`. Wer in mehreren zugeordneten Gruppen ist, erhält die höchste Rolle. Wer in keiner zugeordneten Gruppe ist, erhält `default_role`. Bei ausgeschaltetem `auto_create_users` können sich nur Personen mit vorhandenem Konto anmelden. SSO für ganze E-Mail-Domänen erzwingen und Benutzer automatisch anlegen: siehe [SCIM](scim.de.md).

## Was Benutzer bei Fehlern sehen

Der Browser kehrt mit einer kurzen Meldung zur Anmeldeseite zurück, nie mit einem Stacktrace. Häufige Codes:

- `account_link_refused`: Ein Konto mit dieser E-Mail existiert und ist an einen anderen Anbieter gebunden, oder `link_by_email` ist aus.
- `account_not_found`: Es gibt kein Konto und `auto_create_users` ist aus. Ein Admin soll die Person einladen.
- `domain_not_allowed`: Die E-Mail-Domäne steht nicht in `email_domains` dieses Anbieters.
- `missing_claims`: Der IdP hat weder Subject noch E-Mail geliefert; Attributnamen prüfen.
- `unsolicited`, `replayed`: Die SAML-Antwort gehört zu keiner in diesem Browser gestarteten Anfrage oder wurde schon verwendet. Von der Anmeldeseite neu beginnen.
- `saml_unavailable`: Das Zusatzpaket `[saml]` ist nicht installiert.
- SAML-Signaturfehler: falsches Zertifikat, Zeitabweichung oder eine ACS-URL, die von der registrierten abweicht. Anbieterkarte mit dem IdP vergleichen.
- Nur OIDC: Die Anmeldeanfrage ist abgelaufen, der Anbieter war nicht erreichbar oder hat den Anmeldecode abgelehnt.
