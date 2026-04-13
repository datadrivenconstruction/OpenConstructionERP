/**
 * Single source of truth​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ for the app version.
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
