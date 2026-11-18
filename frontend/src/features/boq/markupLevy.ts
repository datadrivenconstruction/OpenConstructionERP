// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { toNum } from '@/shared/lib/money';

/**
 * Mirror of the server's statutory-levy rules for one markup line
 * (``app.modules.boq.service._calculate_markup_amounts``):
 *
 * - ``metadata.threshold_amount``: the line charges nothing while its base is
 *   at or below the threshold, and its full percentage of the base above it
 *   (a levy on works over a value, not on the excess).
 * - ``metadata.not_compounded``: the amount is not added to the running base
 *   the next cumulative line is a percentage of.
 */
export function levyAdjusted(
  metadata: Record<string, unknown> | null | undefined,
  base: number,
  amount: number,
): { amount: number; compounds: boolean } {
  const meta = metadata ?? {};
  const raw = meta.threshold_amount;
  let out = amount;
  if (raw !== undefined && raw !== null && raw !== '') {
    const threshold = toNum(raw as string | number);
    if (Number.isFinite(threshold) && base <= threshold) out = 0;
  }
  return { amount: out, compounds: meta.not_compounded !== true };
}
