// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Auth hold: while a credential is expired the senders keep every op on the
 * device untouched (no retry count, no rejection) and the UI asks for a
 * re-login. Once the person is back in, `releaseAuthHold` lets the next drain
 * replay the backlog. Two realms because the queues use different credentials:
 * `jwt` for the desktop/PWA session, `field` for the PIN session on /field.
 */

export type AuthRealm = 'jwt' | 'field';

const held = new Map<AuthRealm, string>();
const listeners = new Set<() => void>();

function emit(): void {
  for (const l of [...listeners]) l();
}

export function isAuthHeld(realm?: AuthRealm): boolean {
  return realm ? held.has(realm) : held.size > 0;
}

/** `credential` fingerprints what was refused, so a changed one can lift the hold by itself. */
export function holdAuth(realm: AuthRealm, credential = ''): void {
  if (held.has(realm)) return;
  held.set(realm, credential);
  emit();
}

/** Lift the hold when the credential in use is not the one that was refused. */
export function releaseIfCredentialChanged(realm: AuthRealm, current: string | null): boolean {
  if (!held.has(realm) || !current || held.get(realm) === current) return false;
  releaseAuthHold(realm);
  return true;
}

export function releaseAuthHold(realm: AuthRealm): void {
  if (held.delete(realm)) emit();
}

export function subscribeAuthHold(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function resetAuthHoldForTests(): void {
  held.clear();
  emit();
}
