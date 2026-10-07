# Rotating the JWT signing secret

OpenConstructionERP signs its tokens (access, refresh, password reset and buyer
portal tokens) with HS256 using `JWT_SECRET` (also accepted as `OE_JWT_SECRET`).
Every token carries a `kid` header: the first 16 hex characters of a SHA-256
over a domain-separated copy of the secret. The `kid` identifies the key, it
never reveals it.

Verification uses a key ring: the current `JWT_SECRET` plus any earlier secrets
listed in `JWT_PREVIOUS_SECRETS` (or `OE_JWT_PREVIOUS_SECRETS`), comma-separated.

- A token with a `kid` is checked only against the key with that `kid`. An
  unknown `kid` is rejected.
- A token without a `kid` (issued before key ids existed) is tried against the
  current secret first and then each previous secret.
- New tokens are always signed with the current secret.

Token lifetimes do not change: access tokens live `JWT_EXPIRE_MINUTES` (60 by
default), refresh tokens `JWT_REFRESH_EXPIRE_DAYS` (30 by default).

## When to rotate

Rotate when the secret may have leaked (a copied `.env`, a former operator, a
backup in the wrong hands) or on your own schedule. Rotation without the steps
below logs every user out.

## How to rotate without logging users out

1. Generate a new secret of at least 32 characters:
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. Set the old value as the previous secret and the new value as the current one:

   ```
   JWT_PREVIOUS_SECRETS=<old secret>
   JWT_SECRET=<new secret>
   ```

   If a previous secret is already listed, keep it only if its tokens may still
   be alive, for example `JWT_PREVIOUS_SECRETS=<old secret>,<older secret>`.
3. Restart every application worker so they all hold the same ring.
4. Keep the old secret listed for at least `JWT_REFRESH_EXPIRE_DAYS` (30 days by
   default). Refreshing a session issues tokens signed with the new key, so
   active users move over on their own.
5. After that window, remove the old secret from `JWT_PREVIOUS_SECRETS` and
   restart. Any token still signed with it is then rejected.

If the old secret is known to be compromised, skip the grace period: set the new
`JWT_SECRET` and leave `JWT_PREVIOUS_SECRETS` empty. Everyone has to sign in
again, which is the point.

## What else depends on the secret

The same secret derives the key that encrypts stored credentials such as AI
provider API keys. Decryption also tries every secret in `JWT_PREVIOUS_SECRETS`,
so stored keys stay readable during the grace period. Values saved after the
rotation are encrypted with the new secret, older values are not re-encrypted.
Before you remove the old secret from the list, re-save stored provider keys in
Settings, otherwise they become unreadable and have to be entered again.

A few short-lived signatures use only the current secret and are invalidated by
a rotation: local upload URLs (one hour), module builder review tokens, project
share links and saved-view share links. Share links have to be re-issued after a
rotation.

Session revocation is not affected. Revoking a session or changing a password
refuses tokens whichever key signed them.
