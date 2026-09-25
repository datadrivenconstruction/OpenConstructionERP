// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Opening an authenticated WebSocket without putting the token in the URL.
 *
 * The browser WebSocket API cannot set an Authorization header, so the realtime
 * sockets used to carry the access token as `?token=`. A URL is what every
 * access log writes down, the server's and any proxy's in front of it, so each
 * of those lines held a working session token. The token now goes in the first
 * frame after the socket opens, and the server reads that frame before it
 * sends or accepts anything else (backend `app/core/ws_auth.py`).
 */

/** Absolute ws:// or wss:// URL for a same-origin API path. Carries no token. */
export function socketUrl(path: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${path}`;
}

/** The frame a socket must send first, and before anything else. */
export function authFrame(token: string): string {
  return JSON.stringify({ type: 'auth', token });
}
