// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * OIDC login state: random state, nonce and PKCE verifier kept in
 * sessionStorage between the redirect to the provider and the callback.
 */

const STORAGE_KEY = 'oe_oidc_pending';

function randomString(bytes = 32): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return base64Url(buf);
}

function base64Url(buf: Uint8Array): string {
  let bin = '';
  buf.forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export async function beginOidcLogin(): Promise<{ state: string; nonce: string; codeChallenge: string }> {
  const state = randomString();
  const nonce = randomString();
  const verifier = randomString(48);
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ state, nonce, verifier }));
  return { state, nonce, codeChallenge: base64Url(new Uint8Array(digest)) };
}

/** Returns the pending login if *state* matches, and clears it either way. */
export function takeOidcLogin(state: string | null): { nonce: string; verifier: string } | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  sessionStorage.removeItem(STORAGE_KEY);
  if (!raw || !state) return null;
  try {
    const pending = JSON.parse(raw) as { state: string; nonce: string; verifier: string };
    return pending.state === state ? { nonce: pending.nonce, verifier: pending.verifier } : null;
  } catch {
    return null;
  }
}
