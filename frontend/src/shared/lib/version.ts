// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Single source of truth for the app version.
 *
 * The string is injected by Vite from `package.json` at build time via the
 * `__APP_VERSION__` define (see `vite.config.ts`). Bumping `package.json`
 * automatically updates the sidebar, About page, bug reports, error logs,
 * and update checker — no other files need to change.
 */
export const APP_VERSION: string = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '0.0.0';

/**
 * Stable build identifier for the frontend bundle.  Derived once at
 * design time from a fixed seed so the value is reproducible across
 * rebuilds and across environments — used by the bug reporter and
 * the update checker to disambiguate frontend builds without trusting
 * the package.json version (which can be edited mid-flight).
 */
export const APP_BUILD_FINGERPRINT: string = '34c75c58fc650e71';

/**
 * A release number as integers, or null when the text names no version.
 *
 * Read the way the backend reads one (`_semver_tuple` in `app/main.py`): a
 * leading "v" is dropped, each dotted part keeps only its leading digits, so
 * `5.3.0rc1` reads as 5.3.0. Tolerant on purpose, because the text often comes
 * from a person or a script rather than from us: the update card prints
 * "v18.0.0", so that is what somebody copies into the dismiss key, and a value
 * written with `JSON.stringify` arrives wrapped in quotes.
 */
export function parseVersion(text: string | null | undefined): number[] | null {
  if (typeof text !== 'string') return null;
  const cleaned = text.trim().replace(/^["']+|["']+$/g, '').trim().replace(/^v/i, '');
  if (!/^\d/.test(cleaned)) return null;
  return cleaned.split('.').map((part) => {
    const digits = /^\d+/.exec(part);
    return digits ? parseInt(digits[0], 10) : 0;
  });
}

/**
 * Order two parsed versions: negative when `a` is older, zero when they name
 * the same release, positive when `a` is newer. The shorter one is padded with
 * zeros, so 18.0 and 18.0.0 are the same release.
 */
export function compareVersions(a: readonly number[], b: readonly number[]): number {
  const width = Math.max(a.length, b.length);
  for (let i = 0; i < width; i++) {
    const diff = (a[i] ?? 0) - (b[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

/**
 * Whether `current` is a newer feature release (major.minor) than `lastSeen`.
 *
 * Patch releases do not count: a hotfix carries no new headline to show. A
 * missing `lastSeen` means nothing was acknowledged yet, so the release is new;
 * an unreadable `current` never is.
 */
export function isNewerFeatureRelease(current: string, lastSeen: string | null): boolean {
  const cur = parseVersion(current);
  if (!cur) return false;
  const seen = parseVersion(lastSeen);
  if (!seen) return true;
  return compareVersions(cur.slice(0, 2), seen.slice(0, 2)) > 0;
}
