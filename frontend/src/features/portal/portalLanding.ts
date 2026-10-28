// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// Portal magic-link landing resolution.
//
// A portal invite can carry an explicit `redirect_path` (the inviter chose
// exactly where the user should land). When it does not, we pick a default
// landing by role: subcontractors and suppliers run their work through the
// payment portal, so they default to /portal/payments; everyone else (client,
// investor, consultant, building_user) defaults to the generic role-aware
// /portal/home. Before this, the magic URL was hard-coded to /portal/payments
// for ALL roles, so a client landed on the subcontractor payment portal.

import type { PortalRole } from './api';

/** Generic role-aware landing consumed by App.tsx (`/portal/home`). */
export const PORTAL_HOME_PATH = '/portal/home';

/** Subcontractor / supplier payment portal landing. */
export const PORTAL_PAYMENTS_PATH = '/portal/payments';

/** Roles whose work centres on the payment portal. */
const PAYMENT_FIRST_ROLES: ReadonlySet<string> = new Set<PortalRole>([
  'subcontractor',
  'supplier',
]);

/**
 * The default landing PATH for a role, ignoring any explicit redirect.
 * Subcontractor / supplier -> payments; all other roles -> the generic home.
 */
export function defaultLandingForRole(role: string | null | undefined): string {
  return role && PAYMENT_FIRST_ROLES.has(role)
    ? PORTAL_PAYMENTS_PATH
    : PORTAL_HOME_PATH;
}

/**
 * Resolve the eventual in-app destination AFTER sign-in. This is NOT the
 * magic-link URL itself - that must always hit a consume-capable landing (see
 * `buildMagicLinkUrl`).
 *
 * An explicit, non-empty `redirect_path` always wins (the inviter was
 * deliberate); otherwise we fall back to the per-role default. Used to show the
 * admin where a link will land, and mirrors where the landing page forwards the
 * user once the one-time token has been consumed.
 */
export function resolveLandingPath(
  role: string | null | undefined,
  redirectPath?: string | null,
): string {
  const trimmed = redirectPath?.trim();
  if (trimmed) return trimmed;
  return defaultLandingForRole(role);
}

/**
 * Build the full, ready-to-send magic-link sign-in URL.
 *
 * The URL ALWAYS targets the role's consume-capable landing (`/portal/home` or
 * `/portal/payments`), never the inviter's `redirect_path`. Only those two
 * landings consume the one-time token via POST /portal/auth/consume; pointing
 * the link at an arbitrary deep path (e.g. `/files`) would land the user there
 * unauthenticated and bounce them to /login. The `redirect_path` is stored with
 * the invite server-side and returned by the consume response, so the landing
 * page forwards the now-signed-in user to it (see `resolveLandingPath`).
 *
 * `origin` is the admin's current origin (the backend cannot know the public
 * origin behind a reverse proxy, so the inviter's origin is the correct base
 * for a self-hosted deployment). The token is carried in the query string.
 */
export function buildMagicLinkUrl(
  origin: string,
  token: string,
  role: string | null | undefined,
): string {
  const path = defaultLandingForRole(role);
  return `${origin}${path}?token=${encodeURIComponent(token)}`;
}
