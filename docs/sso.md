# Single sign-on: OIDC and SAML

People sign in with the company identity provider (IdP) instead of a local password. One module, `oe_sso`, handles both protocols. An admin configures one or more providers per tenant in **Settings > Single sign-on**; the login page shows one button per enabled provider. Nothing is set in environment variables.

|  | OIDC | SAML 2.0 |
|---|---|---|
| Extra package | none | `pip install "openconstructionerp[saml]"` |
| Return address at your host | `/auth/oidc/callback` | ACS URL shown on the provider card |
| Groups read from | claim `group_attribute` (default `groups`) | attribute `group_attribute` (default `groups`) |

Client secrets and the IdP certificate are stored in the database, secrets encrypted. The panel never shows a saved secret again; leave the field empty to keep it.

## Add a provider

1. Sign in as an admin and open **Settings > Single sign-on**.
2. Click **Add OpenID Connect** or **Add SAML 2.0**. SAML is offered only when the optional extra is installed (see below).
3. Fill in the fields, save, and register the return address in the IdP.

Fields common to both protocols:

| Field | Meaning |
|---|---|
| `display_name` (Button label) | Text on the login button |
| `slug` (Short name) | Used in URLs, fixed after creation |
| `email_domains` | Only these email domains may sign in through this provider; empty means any |
| `tenant_id` | Optional tenant the provider belongs to |
| `group_attribute` | Claim or attribute holding groups or roles (default `groups`) |
| `group_role_map` | Group name (or Entra group object id, or app role value) to role, one `group=role` per line |
| `default_role` | Role for new people in no mapped group (default `viewer`) |
| `auto_create_users` | Create an account at the first sign-in (default on) |
| `allow_admin_mapping` | Let a group grant `admin` (default off; a mapping to admin is refused otherwise) |
| `link_by_email` | Link a sign-in to an existing local account with the same email (default off) |
| `clock_skew_seconds` | Allowed clock difference (default 120) |
| `enabled` | Show the button on the login page |

## OIDC

Extra fields: `oidc_issuer` (issuer URL), `oidc_client_id`, `oidc_client_secret`, `oidc_scopes` (default `openid email profile`). In the IdP register the redirect URI `https://<your-host>/auth/oidc/callback`. Step by step for Microsoft Entra ID: see [install/azure.md](install/azure.md).

An install that already used the old `OIDC_*` environment settings needs no action: on the first start the data repair `sso_env_oidc_provider` turns them into one provider row (slug `oidc`, same redirect URI), once. After that the environment values are ignored; edit or delete the row in Settings.

## SAML 2.0

1. Install the extra on the server: `pip install "openconstructionerp[saml]"` (it adds `signxml`, pure Python, no system libraries) and restart. Without it the SAML option is hidden in Settings and OIDC keeps working.
2. Add a SAML provider with `saml_idp_entity_id`, `saml_idp_sso_url` (HTTP-Redirect binding), `saml_idp_cert` (the IdP signing certificate, PEM) and optionally `saml_sp_entity_id`, `saml_email_attribute` (default `email`) and `saml_name_attribute` (default `displayName`).
3. The provider card shows the **ACS URL** (`https://<your-host>/api/v1/sso/saml/<slug>/acs/`, HTTP-POST binding), the entity ID and the **metadata URL** (`https://<your-host>/api/v1/sso/saml/<slug>/metadata/`). Give the metadata URL to the IdP, or enter the ACS URL and entity ID by hand.

Sign-in is SP-initiated by default: it starts from the application, and each response is bound to the request that began in the same browser and can be used once. A replayed response is refused. IdP-initiated sign-in works only if the provider option `saml_allow_idp_initiated` is on.

## How people are matched

A person is identified by the pair (issuer, subject) of the provider, not by email. At the first sign-in:

- With `link_by_email` off, a new account is created (if `auto_create_users` is on); an existing local account with the same email is not touched.
- With `link_by_email` on, an existing local account with that email is linked. For OIDC the provider must report `email_verified`.
- An account already bound to another IdP is never relinked; the sign-in fails with `account_link_refused`.

## Mapping groups to roles

`group_role_map` maps a group to a role, for example `estimators=editor`, `site-managers=manager`, `finance=viewer`. A person in several mapped groups gets the most privileged role. A person in no mapped group gets `default_role`. With `auto_create_users` off only people who already have an account can sign in. To enforce SSO for whole email domains and provision users automatically, see [SCIM](scim.md).

## What users see when sign-in fails

The browser returns to the login page with a short message, never a stack trace. Common codes:

- `account_link_refused`: an account with this email exists and is bound to another provider, or `link_by_email` is off.
- `account_not_found`: no account exists and `auto_create_users` is off. Ask an admin to invite the person.
- `domain_not_allowed`: the email domain is not in `email_domains` of this provider.
- `missing_claims`: the IdP sent no subject or email; check the attribute names.
- `unsolicited`, `replayed`: the SAML response did not match a request started in this browser, or was already used. Start again from the login page.
- `saml_unavailable`: the `[saml]` extra is not installed.
- SAML signature errors: wrong certificate, clock drift, or an ACS URL that differs from the one registered. Compare the provider card with the IdP.
- OIDC only: the sign-in request expired, the provider could not be reached, or it rejected the sign-in code.
