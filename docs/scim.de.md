# SCIM-2.0-Benutzerbereitstellung

Verbinden Sie Ihren Identity Provider (IdP) einmal. Danach erscheinen Personen in OpenConstructionERP, wechseln mit ihrer Gruppe die Rolle und verlieren beim Ausscheiden aus dem Unternehmen den Zugang.

## Einrichten

1. Als Admin anmelden und **Einstellungen > Identity** öffnen.
2. Die **SCIM-Basis-URL** kopieren (`https://<ihr-host>/scim/v2`).
3. **Token erzeugen** wählen. Das Token ist ein API-Schlüssel mit dem Scope `scim`, Ihnen zugeordnet. Es wird nur einmal angezeigt und gehört nur in den IdP.
4. Beides im IdP eintragen:
   - **Microsoft Entra ID**: Unternehmensanwendung, Bereitstellung, Modus Automatisch. Mandanten-URL = Basis-URL, Geheimes Token = das Token. Verbindung testen, Bereitstellung starten. `userPrincipalName` auf `userName`, `objectId` auf `externalId` abbilden.
   - **Okta**: Anwendung, Provisioning, SCIM-Connector. Basis-URL, eindeutiges Feld `userName`, Authentifizierung per HTTP-Header (Bearer-Token). Benutzer anlegen, aktualisieren und deaktivieren aktivieren.
   - **Keycloak**: Keycloak hat keinen eingebauten SCIM-Client. Eine SCIM-Provisioning-Erweiterung mit derselben URL und demselben Token verwenden.
5. Gruppen aus dem IdP übertragen. In **Einstellungen > Identity** jeder Gruppe, die eine Rolle tragen soll, eine Rolle zuweisen. Gruppen ohne Rolle sind reine Bezeichnungen.

## Was der IdP darf und was nicht

- Benutzer und Gruppen anlegen, ändern, entfernen und Mitgliedschaften ändern. Wiederholtes Anlegen ist unschädlich: Es wird über `externalId`, dann über die E-Mail zugeordnet und ein vorhandenes lokales Konto übernommen.
- Entfernen (DELETE oder `active=false`) deaktiviert das Konto. Die Zeile bleibt erhalten. Sitzungen werden widerrufen und API-Schlüssel im selben Schritt abgeschaltet; das Audit-Log enthält `scim.user.deactivate`. Bei erneuter Aktivierung kehrt der Zugang zurück, API-Schlüssel bleiben aus und müssen neu ausgestellt werden.
- Der IdP kann nie eine Rolle senden. Die Rolle kommt nur aus einer Gruppe, die ein Admin in der Oberfläche zugeordnet hat. Bei mehreren Gruppen gilt die höchste Rolle; nach der letzten zugeordneten Gruppe gilt wieder `OIDC_DEFAULT_ROLE`.
- Eine Gruppe auf **admin** abzubilden ist nur mit `SCIM_ALLOW_ADMIN_GROUPS=true` möglich. Der letzte aktive Admin kann über SCIM nie deaktiviert oder herabgestuft werden.

## Single Sign-on erzwingen

`SSO_ENFORCED_DOMAINS=firma.example,tochter.example` lässt Passwort-Anmeldung, Selbstregistrierung und Passwort-Reset für diese E-Mail-Domains mit 403 `auth.sso_required` antworten. Ein Admin mit `metadata.break_glass = true` ist ausgenommen, damit ein ausgefallener IdP niemanden aussperrt. Zusammen mit `OIDC_ENABLED=true` verwenden; sonst warnt der Server beim Start.

## Unterstützt und nicht unterstützt

Unterstützt: Users und Groups, GET/POST/PUT/PATCH/DELETE, `filter` mit `eq` auf `userName`, `externalId` (Benutzer) und `displayName` (Gruppen), seitenweiser Abruf mit `startIndex` und `count` (höchstens 100), PatchOp `add`, `replace`, `remove` einschließlich des Entra-Wertobjekts ohne Pfad.

Nicht unterstützt: SAML (die SAML-zu-OIDC-Brücke des IdP davorschalten und OIDC-Anmeldung nutzen), Bulk, ETag, Sortierung, Passwortabgleich (`changePassword`), das Enterprise-Erweiterungsschema, verschachtelte Gruppen und weitere Filteroperatoren (Antwort 400 `invalidFilter`).
