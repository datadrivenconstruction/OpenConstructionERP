// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The role vocabulary the UI borrows from the backend permission registry.
 *
 * `backend/app/core/permissions.py` is the authority: it resolves a role
 * through `ROLE_ALIASES` and then compares it against `ROLE_HIERARCHY`, and
 * every server-side check goes through that pair. The UI needs the same
 * vocabulary only to decide what to OFFER, never to decide what is permitted,
 * so a copy that drifts shows the wrong affordance rather than granting
 * access. Wrong affordances are still expensive: a button hidden from the one
 * role the backend accepts reads as a broken feature, and a button offered to
 * a role the backend rejects reads as a broken backend.
 *
 * This file exists because the same two tables had been typed out by hand in
 * three feature files, which is three chances to update two of them. What is
 * shared here is the DATA. The wrappers around it deliberately are not: see
 * `normalizeRole` below for the one decision a caller has to make for itself.
 *
 * `scripts/check_role_mirrors_match_the_backend.py` compares both tables
 * against the backend and fails if either drifts, or if a second copy of
 * either appears anywhere under `frontend/src`.
 */

/**
 * Legacy and industry role names that resolve to a canonical role.
 *
 * These are not decorative. A user whose stored role is `estimator` is granted
 * exactly what an `editor` is granted, so a UI that does not know the alias
 * hides working features from them.
 */
export const ROLE_ALIASES: Readonly<Record<string, string>> = {
  estimator: 'editor',
  quantity_surveyor: 'editor',
  qs: 'editor',
  user: 'editor',
  superuser: 'admin',
  owner: 'admin',
  readonly: 'viewer',
  guest: 'viewer',
};

/**
 * Privilege ranking, higher is more access. Mirrors `ROLE_HIERARCHY`.
 *
 * Declared `as const` rather than as a `Record` so that `ROLE_RANK.editor`
 * keeps its literal type: under `noUncheckedIndexedAccess` an index signature
 * would make every lookup `number | undefined` and push that check onto every
 * caller that names a rank statically.
 */
export const ROLE_RANK = {
  field_worker: -2,
  site_foreman: -1,
  site_inspector: 0,
  viewer: 0,
  editor: 1,
  manager: 2,
  admin: 3,
} as const;

/**
 * Resolve a role string to its canonical name, for callers that compare the
 * result against named roles.
 *
 * An absent role becomes `viewer`, which is the least privileged role that
 * still names something, so a caller comparing against `editor` or `admin`
 * denies. A role that is neither canonical nor an alias comes back unchanged;
 * it matches no comparison and therefore also denies.
 *
 * A caller that must tell "no role at all" apart from "the viewer role" cannot
 * use this, because here the two arrive as the same string. `canGrant` in
 * `features/ai-agents/components/ToolPanel.tsx` is such a caller: it compares
 * RANKS rather than names, `viewer` has rank 0, and its cheapest permissions
 * need rank 0, so mapping an absent role to `viewer` there would turn a denial
 * into a grant. It resolves through `ROLE_ALIASES` directly instead, leaving an
 * unknown role with no rank at all.
 */
export function normalizeRole(role: string | null | undefined): string {
  const r = (role ?? 'viewer').trim().toLowerCase();
  return ROLE_ALIASES[r] ?? r;
}
