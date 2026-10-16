// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Whether the signed-in user may delete a bill.
 *
 * Mirrors the backend rule on `DELETE /v1/boq/boqs/{id}`: `boq.delete`
 * (editor and above) deletes any bill, and the user who started a bill may
 * delete that one whatever their role. A viewer can start an estimate, so a
 * viewer must be able to remove it again; a colleague's bill stays out of
 * reach. The backend decides; this only keeps the bin off rows the click
 * would be refused on.
 */

import { roleHasPermission } from '@/shared/lib/permissionGates';

export function canDeleteBoq(
  role: string | null | undefined,
  userId: string | null | undefined,
  boq: { created_by?: string | null },
): boolean {
  if (roleHasPermission(role, 'boq.delete')) return true;
  const author = (boq.created_by ?? '').trim().toLowerCase();
  const me = (userId ?? '').trim().toLowerCase();
  return author !== '' && author === me;
}
