// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Whether the signed-in role ranks at least `minRole`, and the sentence to show
 * on an action it cannot take. For modules whose routes check one role level
 * (their permission registry row names it) and have no named gate yet.
 * The backend stays the authority; this only decides enabled or disabled.
 */

import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/stores/useAuthStore';
import { roleAtLeast, roleReasonText, type ActionRole } from './permissionReason';

export interface RoleGate {
  allowed: boolean;
  /** Undefined when allowed; pass to `Button`'s `disabledReason` or a control's `title`. */
  reason: string | undefined;
}

export function useRoleGate(minRole: ActionRole): RoleGate {
  const { t } = useTranslation();
  const role = useAuthStore((s) => s.userRole);
  const allowed = roleAtLeast(role, minRole);
  return { allowed, reason: allowed ? undefined : roleReasonText(t, minRole) };
}
