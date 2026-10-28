// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Role sets mirroring the property_dev permission registry. These decide
// whether a control is worth putting on screen. They are not the wall: the
// backend re-checks every request and owns the answer. What they buy is that
// the UI neither offers a control the server would refuse, nor hides one the
// server would now serve.
//
// Each constant is named after the PERMISSION it mirrors rather than after
// the roles it happens to contain, because the roles are a derived set. A
// permission at EDITOR level also admits MANAGER and ADMIN through the rank
// hierarchy, plus every legacy alias that resolves into one of those, so the
// list here is longer than the mapping on the backend and will change
// whenever an alias is added. Naming the permission keeps the call sites
// honest about what they are gating and lets a later change swap the array
// for a real permission lookup without touching them.
//
// Kept equal to the backend by scripts/check_role_mirrors_match_the_backend.py,
// which resolves the closure through the same registry the request path uses
// and asserts set equality in both directions.

/**
 * Roles admitted by `property_dev.owner_scoped_delete`, which sits at EDITOR
 * level. The low level is deliberate: on those routes the real wall is the
 * ownership check in the handler, which only the owning project passes, the
 * global admin role included. Role is therefore a coarse pre-filter here and
 * nothing more.
 */
export const ROLES_WITH_OWNER_SCOPED_DELETE: readonly string[] = [
  'admin',
  'manager',
  'editor',
  // Legacy and industry aliases that resolve to one of the three above.
  'superuser',
  'owner',
  'estimator',
  'quantity_surveyor',
  'qs',
  'user',
];

/**
 * Roles admitted by `property_dev.lead.delete`, which sits at EDITOR level
 * the same as the owner-scoped deletes. The two constants remain separate
 * because the sets coincide today but are derived from different permissions
 * and may diverge if one of them is raised.
 */
export const ROLES_WITH_LEAD_DELETE: readonly string[] = [
  'admin',
  'manager',
  'editor',
  // Legacy and industry aliases that resolve to one of the three above.
  'superuser',
  'owner',
  'estimator',
  'quantity_surveyor',
  'qs',
  'user',
];
