/**
 * Base-aware URLs for files in `public/` (brand marks, role photos, fonts).
 *
 * The public demo is served under `/demo` while the browser keeps that prefix,
 * so a root-absolute brand-kit path would hit the marketing site. Desktop,
 * localhost and the pip wheel serve at the root and get the path unchanged.
 */
const DEMO_PREFIX = '/demo';

/** Sub-path the app is mounted under: `/demo` on the public demo, otherwise ''. */
export function appBasePath(): string {
  if (typeof window === 'undefined') return '';
  const p = window.location.pathname;
  return p === DEMO_PREFIX || p.startsWith(`${DEMO_PREFIX}/`) ? DEMO_PREFIX : '';
}

/** Resolve a `public/` path (with or without leading slash) against the app base. */
export function publicAsset(path: string): string {
  return `${appBasePath()}/${path.replace(/^\/+/, '')}`;
}
