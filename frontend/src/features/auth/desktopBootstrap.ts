/**
 * Desktop first-run bootstrap decision logic.
 *
 * In the native (Tauri) build the app ships as a single-user local workspace.
 * Rather than ask the owner to invent credentials on first launch, the desktop
 * shell auto-provisions a local owner account and signs in silently. This file
 * holds the *pure* decision functions so the side-effecting flow in
 * {@link ../auth/LoginPage} stays thin and the rules are unit-testable.
 *
 * Two gates exist on purpose:
 *  - {@link shouldQueryFirstRun} decides whether we even hit the network. It is
 *    a cheap client-only check (running in Tauri, no token yet, the user has
 *    not explicitly logged out this session).
 *  - {@link shouldAttemptDesktopBootstrap} folds the server's `/auth/first-run`
 *    answer into the same client gates and is the single source of truth for
 *    "POST desktop-bootstrap now".
 */

/** Shape of `GET /api/v1/auth/first-run` (locked contract). */
export interface FirstRunStatus {
  desktop_mode: boolean;
  fresh_install: boolean;
  has_local_account: boolean;
  onboarding_completed: boolean | null;
}

/**
 * Cheap client-only gate: should we query `/auth/first-run` at all?
 *
 * True only when running inside the desktop shell, with no stored access token,
 * and the user has not chosen to log in manually this session (the logout
 * action sets `oe_manual_login="1"` so a deliberate sign-out is respected and
 * the form is shown instead of silently re-bootstrapping).
 */
export function shouldQueryFirstRun(
  tauri: boolean,
  hasToken: boolean,
  manualFlag: string | null,
): boolean {
  return tauri && !hasToken && manualFlag !== '1';
}

/**
 * Full decision: should we POST `/auth/desktop-bootstrap`?
 *
 * Combines the server status with the same client gates as
 * {@link shouldQueryFirstRun}. We only bootstrap when the backend confirms it
 * is in desktop mode and the workspace is either a clean install or already
 * owns a local account - never when real registered users exist but no local
 * owner does (that path must fall through to the normal login form).
 *
 * @param status     parsed `/auth/first-run` response, or `null` on any fetch
 *                   / parse failure (treated as "do not bootstrap").
 * @param hasToken   whether an access token is already stored.
 * @param manualFlag value of `sessionStorage["oe_manual_login"]`.
 */
export function shouldAttemptDesktopBootstrap(
  status: FirstRunStatus | null,
  hasToken: boolean,
  manualFlag: string | null,
): boolean {
  if (!status) return false;
  if (hasToken) return false;
  if (manualFlag === '1') return false;
  if (!status.desktop_mode) return false;
  return status.fresh_install || status.has_local_account;
}
