// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Browser helpers that stay safe outside a secure context.
 *
 * Several Web APIs only exist when the page is a "secure context": HTTPS, or
 * http://localhost / 127.0.0.1. A self-hosted OpenConstructionERP reached over
 * plain http://<server-ip> is NOT a secure context, so `crypto.randomUUID` and
 * `navigator.clipboard` are simply `undefined` there. Calling them throws
 * (e.g. "crypto.randomUUID is not a function" when uploading a DWG), which used
 * to break core flows on LAN / on-prem deployments.
 *
 * These wrappers prefer the native API when present and fall back to something
 * that works everywhere, so nothing crashes on http origins.
 */

/**
 * Return a RFC-4122 v4 UUID.
 *
 * Order of preference:
 *  1. `crypto.randomUUID()` (secure contexts).
 *  2. `crypto.getRandomValues()` (available in insecure contexts too) for a
 *     proper random v4.
 *  3. `Math.random()` as a last resort so an id is always produced.
 */
export function uuid(): string {
  const c: Crypto | undefined = typeof globalThis !== 'undefined' ? globalThis.crypto : undefined;

  if (c && typeof c.randomUUID === 'function') {
    try {
      return c.randomUUID();
    } catch {
      /* fall through to the manual generators */
    }
  }

  if (c && typeof c.getRandomValues === 'function') {
    const bytes = new Uint8Array(16);
    c.getRandomValues(bytes);
    bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40; // version 4
    bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80; // variant 10xx
    // Map each byte to two hex chars without unchecked index reads, then slice
    // into the 8-4-4-4-12 UUID grouping. Array.from's map callback yields a
    // guaranteed `number`, so this stays clean under noUncheckedIndexedAccess.
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0'));
    return (
      hex.slice(0, 4).join('') +
      '-' +
      hex.slice(4, 6).join('') +
      '-' +
      hex.slice(6, 8).join('') +
      '-' +
      hex.slice(8, 10).join('') +
      '-' +
      hex.slice(10, 16).join('')
    );
  }

  // Non-cryptographic last resort. Good enough for client-side ids/keys.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0;
    const v = ch === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Copy text to the clipboard, returning whether it succeeded.
 *
 * Uses the async Clipboard API when available (secure contexts) and falls back
 * to a hidden textarea + `document.execCommand('copy')`, which still works on
 * plain-http origins. Never throws.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      /* fall through to the legacy path */
    }
  }

  if (typeof document === 'undefined') return false;

  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-9999px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

/**
 * Read text from the clipboard. Returns an empty string when the API is
 * unavailable (insecure context) instead of throwing, so callers can degrade
 * gracefully (e.g. paste-from-clipboard buttons simply do nothing).
 */
export async function readClipboard(): Promise<string> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.readText) {
    try {
      return await navigator.clipboard.readText();
    } catch {
      return '';
    }
  }
  return '';
}
