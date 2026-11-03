# SCIM 2.0 user provisioning

Connect your identity provider (IdP) once. People then appear in OpenConstructionERP, change role when their group changes, and lose access when they leave the company.

## Set up

1. Sign in as an admin and open **Settings > Identity**.
2. Copy the **SCIM base URL** (`https://<your-host>/scim/v2`).
3. Click **Generate token**. The token is an API key with the `scim` scope owned by you; it is shown once. Keep it in your IdP only.
4. Paste both into the IdP:
   - **Microsoft Entra ID**: Enterprise application, Provisioning, mode Automatic. Tenant URL = base URL, Secret token = the token. Test the connection, then start provisioning. Map `userPrincipalName` to `userName` and `objectId` to `externalId`.
   - **Okta**: Application, Provisioning, SCIM connector. Base URL, unique identifier field `userName`, authentication HTTP Header (bearer token). Enable Create, Update and Deactivate users.
   - **Keycloak**: Keycloak has no built-in SCIM client. Use a SCIM provisioning extension and give it the same URL and token.
5. Push groups from the IdP. In **Settings > Identity** choose a role for each group that should carry one. Groups without a role are labels only.

## What the IdP can and cannot do

- Create, update and remove users and groups, and change group membership. A repeated create is safe: it matches by `externalId`, then by email, and adopts an existing local account.
- Removing a user (DELETE or `active=false`) deactivates the account. The row stays. Sessions are revoked and API keys switched off in the same step, and the audit log records `scim.user.deactivate`. Activating the user again restores access, but API keys stay off and must be issued again.
- The IdP can never send a role. A role comes only from a group an admin mapped in the UI. A user in several mapped groups gets the most privileged role; leaving the last mapped group returns the user to `OIDC_DEFAULT_ROLE`.
- Mapping a group to **admin** is refused unless `SCIM_ALLOW_ADMIN_GROUPS=true`. The last active admin can never be deactivated or demoted through SCIM.

## Enforcing single sign-on

`SSO_ENFORCED_DOMAINS=corp.example,subsidiary.example` makes password sign-in, self-registration and password reset answer 403 `auth.sso_required` for those email domains. An admin whose user record has `metadata.break_glass = true` is exempt, so a broken IdP cannot lock everybody out. Use it together with `OIDC_ENABLED=true`; the server warns at start-up if it is not set.

## Supported and not supported

Supported: Users and Groups, GET/POST/PUT/PATCH/DELETE, `filter` with `eq` on `userName`, `externalId` (users) and `displayName` (groups), paging with `startIndex` and `count` (at most 100), PatchOp `add`, `replace`, `remove` including the Entra style value object without a path.

Not supported: SAML (put the SAML-to-OIDC bridge of your IdP in front, then use OIDC sign-in), Bulk, ETag, sorting, password sync (`changePassword`), the enterprise extension schema, nested groups and other filter operators (they answer 400 `invalidFilter`).
