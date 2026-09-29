// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Named permission gates for the calls a low-privilege role is refused.
 *
 * The backend stays the only authority: every route still checks its own
 * permission, and nothing here grants anything. What this decides is whether
 * the UI FIRES a call at all. A viewer who opens a page that quietly asks for
 * the user directory or the payroll rollup gets a 403 they did nothing to
 * cause, the widget renders an error, and the client-error report files it as
 * a defect. Asking first, and not firing a request the role cannot pass, keeps
 * the page usable and the report honest.
 *
 * Each entry names the backend permission it mirrors and the lowest role that
 * registry grants it to. The name matters: a bare "manager or above" check at
 * a call site says nothing about WHICH permission it follows, so nothing could
 * notice when that permission moves. `scripts/check_role_mirrors_match_the_backend.py`
 * compares every row here against `permission_registry` and fails on drift in
 * either direction.
 *
 * Add a row for a new gate rather than comparing ranks inline.
 */

import { useAuthStore } from '@/stores/useAuthStore';
import { ROLE_RANK, normalizeRole } from './roles';

type RankedRole = keyof typeof ROLE_RANK;

export const PERMISSION_MIN_ROLE = {
  'users.list': 'manager',
  'payroll.read': 'manager',
  'certified_payroll.read': 'manager',
  'ai.estimate': 'editor',
  'audit.view': 'manager',
} as const satisfies Record<string, RankedRole>;

export type GatedPermission = keyof typeof PERMISSION_MIN_ROLE;

/**
 * Whether `role` would pass `permission` on the backend.
 *
 * An absent role resolves to `viewer` through `normalizeRole`, and every row
 * above needs more than a viewer, so "no role yet" denies. A role that is
 * neither canonical nor an alias has no rank and also denies.
 */
export function roleHasPermission(role: string | null | undefined, permission: GatedPermission): boolean {
  const rank = (ROLE_RANK as Readonly<Record<string, number>>)[normalizeRole(role)];
  if (rank === undefined) return false;
  return rank >= ROLE_RANK[PERMISSION_MIN_ROLE[permission]];
}

/** `roleHasPermission` for the signed-in user, from the live role in the auth store. */
export function useHasPermission(permission: GatedPermission): boolean {
  const role = useAuthStore((s) => s.userRole);
  return roleHasPermission(role, permission);
}
