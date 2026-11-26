// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The sentence a disabled action shows to a user whose role cannot take it.
 *
 * What a user may read never depends on what they may write: a viewer sees the
 * same lists, sections and buttons as an editor, and an action they cannot take
 * stays on screen, disabled, saying who can. These helpers turn "the role this
 * action needs" into that sentence, so every page words it the same way.
 */

import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useAuthStore } from '@/stores/useAuthStore';
import { PERMISSION_MIN_ROLE, roleHasPermission, type GatedPermission } from './permissionGates';
import { ROLE_RANK, normalizeRole } from './roles';

/** The roles an action can require, lowest first. */
export type ActionRole = 'editor' | 'manager' | 'admin';

const REASON_DEFAULTS: Record<ActionRole, string> = {
  editor: 'Only an editor, manager or administrator can do this.',
  manager: 'Only a manager or administrator can do this.',
  admin: 'Only an administrator can do this.',
};

/** The translated reason for an action that needs `minRole`. */
export function roleReasonText(t: TFunction, minRole: ActionRole): string {
  return t(`permissions.reason.${minRole}_only`, { defaultValue: REASON_DEFAULTS[minRole] });
}

/** Whether `role` ranks at least `minRole`. An unknown role ranks nowhere and fails. */
export function roleAtLeast(role: string | null | undefined, minRole: ActionRole): boolean {
  const rank = (ROLE_RANK as Readonly<Record<string, number>>)[normalizeRole(role)];
  return rank !== undefined && rank >= ROLE_RANK[minRole];
}

/**
 * The reason to show on an action gated by `allowed`, or `undefined` when the
 * user may take it. For pages that already compute their own `canEdit`.
 */
export function useRoleReason(allowed: boolean, minRole: ActionRole): string | undefined {
  const { t } = useTranslation();
  return allowed ? undefined : roleReasonText(t, minRole);
}

/**
 * The reason to show on an action that needs `permission`, or `undefined` when
 * the signed-in user's role passes it. Pass the result to `Button`'s
 * `disabledReason`, or to a raw control's `title` alongside `disabled`.
 */
export function usePermissionReason(permission: GatedPermission): string | undefined {
  const { t } = useTranslation();
  const role = useAuthStore((s) => s.userRole);
  if (roleHasPermission(role, permission)) return undefined;
  return roleReasonText(t, PERMISSION_MIN_ROLE[permission]);
}
