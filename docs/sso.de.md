# Single Sign-on: OIDC und SAML

Die Anmeldung erfolgt über den Identity Provider (IdP) des Unternehmens statt über ein lokales Passwort. Beide Protokolle werden gleichwertig unterstützt. Nehmen Sie das Protokoll, das Ihr IdP anbietet; beide lassen sich auch gleichzeitig einrichten, die Anmeldeseite zeigt dann die passende Schaltfläche.

|  | OIDC | SAML 2.0 |
|---|---|---|
| Zusatzpaket | keines | `pip install "openconstructionerp[saml]"` |
| Aktivieren | `OIDC_ENABLED=true` | `SAML_ENABLED=true` |
| Rücksprungadresse auf Ihrem Host | `/auth/oidc/callback` | `/api/v1/users/auth/saml/acs/` (ACS-URL) |
| Rollen aus | `OIDC_ROLE_CLAIMS` (Standard `groups,roles`) | `SAML_ROLE_ATTRIBUTE` (Standard `groups`) |

Nach jeder Änderung einer Einstellung den Server neu starten.

## OIDC

`OIDC_ISSUER_URL`, `OIDC_CLIENT_ID` und `OIDC_CLIENT_SECRET` setzen. Optional: `OIDC_SCOPES` (Standard `openid email profile`), `OIDC_AUTO_CREATE_USERS` (Standard true), `OIDC_DEFAULT_ROLE` (Standard `viewer`). Im IdP die Redirect-URI `https://<ihr-host>/auth/oidc/callback` eintragen. Schritt für Schritt für Microsoft Entra ID: siehe [install/azure.de.md](install/azure.de.md).

## SAML 2.0

1. Das Zusatzpaket auf dem Server installieren: `pip install "openconstructionerp[saml]"`. Es bringt `python3-saml` und `xmlsec` mit; unter Linux wird dafür die Systembibliothek libxmlsec1 benötigt. Ohne das Paket zeigt die Anmeldung "SAML-Anmeldung ist auf diesem Server nicht verfügbar".
2. Im IdP eine SAML-Anwendung anlegen. Die **ACS-URL** (Assertion Consumer Service, HTTP-POST-Binding) auf `https://<ihr-host>/api/v1/users/auth/saml/acs/` setzen und die Entity-ID auf den Wert von `SAML_SP_ENTITY_ID`.
3. Diese Variablen setzen:

| Variable | Bedeutung |
|---|---|
| `SAML_ENABLED` | `true` schaltet die SAML-Anmeldung ein |
| `SAML_SP_ENTITY_ID` | Entity-ID dieser Anwendung, wie im IdP eingetragen |
| `SAML_ACS_URL` | Die ACS-URL von oben, genau wie im IdP eingetragen |
| `SAML_IDP_ENTITY_ID` | Entity-ID (Aussteller) des IdP |
| `SAML_IDP_SSO_URL` | Single-Sign-on-URL des IdP (HTTP-Redirect-Binding) |
| `SAML_IDP_X509_CERT` | Signaturzertifikat des IdP, PEM-Text ohne Kopf- und Fußzeilen |
| `SAML_EMAIL_ATTRIBUTE` | Attribut mit der E-Mail-Adresse (Standard `email`) |
| `SAML_NAME_ATTRIBUTE` | Attribut mit dem Anzeigenamen (Standard `displayName`) |
| `SAML_ROLE_ATTRIBUTE` | Attribut mit Gruppen oder Rollen (Standard `groups`) |

SAML wird nur angeboten, wenn SSO-URL, IdP-Entity-ID, Zertifikat und ACS-URL gesetzt sind. Die Anmeldung beginnt in der Anwendung (SP-initiiert).

## Gruppen auf Rollen abbilden

Beide Protokolle nutzen `OIDC_GROUP_ROLE_MAP`, ein JSON-Objekt von Gruppenname (oder Entra-Gruppen-Objekt-ID oder App-Rollenwert) auf eine Rolle:

    OIDC_GROUP_ROLE_MAP={"estimators":"editor","site-managers":"manager","finance":"viewer"}

Wer in mehreren zugeordneten Gruppen ist, erhält die höchste Rolle. Ein neuer Benutzer ohne zugeordnete Gruppe erhält `OIDC_DEFAULT_ROLE`. Mit `OIDC_AUTO_CREATE_USERS=false` können sich nur Personen mit vorhandenem Konto anmelden. SSO für ganze E-Mail-Domänen erzwingen und Benutzer automatisch bereitstellen: siehe [SCIM](scim.de.md).

## Was Benutzer bei einem Fehler sehen

Der Browser kehrt mit einer kurzen Meldung zur Anmeldeseite zurück, nie mit einem Stacktrace:

- Die Antwort des Identity Providers konnte nicht verifiziert werden: falsches Zertifikat, Zeitabweichung oder eine ACS-URL, die von der registrierten abweicht. Der Admin vergleicht die `SAML_*`-Werte mit dem IdP.
- Für diese Anmeldung existiert kein Konto und die automatische Kontoerstellung ist aus: einen Admin um eine Einladung bitten.
- Der Identity Provider hat keine Benutzer-ID oder E-Mail geliefert: Attributnamen prüfen.
- SAML-Anmeldung ist auf diesem Server nicht verfügbar: das Zusatzpaket `[saml]` fehlt.
- Nur OIDC: die Anmeldeanfrage ist abgelaufen (erneut versuchen), der Provider war nicht erreichbar oder hat den Anmeldecode abgelehnt.
