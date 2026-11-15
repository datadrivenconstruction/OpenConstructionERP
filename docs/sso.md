# Single sign-on: OIDC and SAML

People sign in with the company identity provider (IdP) instead of a local password. Two protocols are supported side by side. Pick the one your IdP offers; both can be configured, and the login page shows the matching button.

|  | OIDC | SAML 2.0 |
|---|---|---|
| Extra package | none | `pip install "openconstructionerp[saml]"` |
| Enable | `OIDC_ENABLED=true` | `SAML_ENABLED=true` |
| Return address at your host | `/auth/oidc/callback` | `/api/v1/users/auth/saml/acs/` (ACS URL) |
| Roles read from | `OIDC_ROLE_CLAIMS` (default `groups,roles`) | `SAML_ROLE_ATTRIBUTE` (default `groups`) |

Restart the server after changing a setting.

## OIDC

Set `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`. Optional: `OIDC_SCOPES` (default `openid email profile`), `OIDC_AUTO_CREATE_USERS` (default true), `OIDC_DEFAULT_ROLE` (default `viewer`). In the IdP register the redirect URI `https://<your-host>/auth/oidc/callback`. Step by step for Microsoft Entra ID: see [install/azure.md](install/azure.md).

## SAML 2.0

1. Install the extra on the server: `pip install "openconstructionerp[saml]"`. It pulls in `python3-saml` and `xmlsec`, which need the system library libxmlsec1 on Linux. Without the extra the login page shows "SAML sign-in is not available on this server".
2. In the IdP create a SAML application. Set its **ACS URL** (assertion consumer service, HTTP-POST binding) to `https://<your-host>/api/v1/users/auth/saml/acs/` and its entity ID to the value you use for `SAML_SP_ENTITY_ID`.
3. Set these variables:

| Variable | Meaning |
|---|---|
| `SAML_ENABLED` | `true` to turn SAML sign-in on |
| `SAML_SP_ENTITY_ID` | Entity ID of this application, as registered in the IdP |
| `SAML_ACS_URL` | The ACS URL above, exactly as registered |
| `SAML_IDP_ENTITY_ID` | Entity ID (issuer) of the IdP |
| `SAML_IDP_SSO_URL` | The IdP single sign-on URL (HTTP-Redirect binding) |
| `SAML_IDP_X509_CERT` | The IdP signing certificate, PEM text without header lines |
| `SAML_EMAIL_ATTRIBUTE` | Attribute holding the email (default `email`) |
| `SAML_NAME_ATTRIBUTE` | Attribute holding the display name (default `displayName`) |
| `SAML_ROLE_ATTRIBUTE` | Attribute holding groups or roles (default `groups`) |

SAML is offered only when the SSO URL, IdP entity ID, certificate and ACS URL are all set. Sign-in starts from the application (SP-initiated).

## Mapping groups to roles

Both protocols use `OIDC_GROUP_ROLE_MAP`, a JSON object from group name (or Entra group object id, or app role value) to a role:

    OIDC_GROUP_ROLE_MAP={"estimators":"editor","site-managers":"manager","finance":"viewer"}

A person in several mapped groups gets the most privileged role. A new user in no mapped group gets `OIDC_DEFAULT_ROLE`. With `OIDC_AUTO_CREATE_USERS=false` only people who already have an account can sign in. To enforce SSO for whole email domains and provision users automatically, see [SCIM](scim.md).

## What users see when sign-in fails

The browser returns to the login page with a short message, never a stack trace:

- The identity provider response could not be verified: wrong certificate, clock drift, or an ACS URL that differs from the one registered. Ask the admin to compare the `SAML_*` values with the IdP.
- No account exists for this sign-in and automatic account creation is off: ask an admin to invite the person.
- The identity provider did not return a user id or email: check the attribute names.
- SAML sign-in is not available on this server: the `[saml]` extra is not installed.
- OIDC only: the sign-in request expired (try again), the provider could not be reached, or it rejected the sign-in code.
