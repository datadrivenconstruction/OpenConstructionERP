// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { BadgeVariant } from '@/shared/ui';

/** Badge tone for agreement and order statuses (shared vocabulary). */
export function statusVariant(status: string): BadgeVariant {
  switch (status) {
    case 'active':
    case 'issued':
    case 'in_progress':
      return 'blue';
    case 'signed':
    case 'measured':
      return 'purple';
    case 'claimed':
    case 'closed':
      return 'success';
    case 'exhausted':
      return 'warning';
    case 'expired':
    case 'cancelled':
      return 'error';
    default:
      return 'neutral';
  }
}

/** Parse "code TAB qty" lines pasted from a spreadsheet; blank and unreadable rows are skipped. */
export function parsePastedLines(text: string): { code: string; quantity: string }[] {
  const out: { code: string; quantity: string }[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const cells = raw.split('\t').map((c) => c.trim());
    if (cells.length < 2 || !cells[0]) continue;
    const qty = cells[cells.length - 1]!.replace(/\s/g, '').replace(',', '.');
    if (!/^\d+(\.\d+)?$/.test(qty) || Number(qty) <= 0) continue;
    out.push({ code: cells[0], quantity: qty });
  }
  return out;
}

// Pack fields that are flags or order-level dates, not values typed on the agreement.
const NOT_AGREEMENT_INPUTS = new Set([
  'measurement_preset',
  'estimated_value',
  'max_value_required',
  'min_value_required',
  'task_order_starting_date',
  'task_order_completion_date',
]);

/** The pack fields a user types on the agreement itself. */
export function agreementPackInputs(packFields: string[] | undefined): string[] {
  return (packFields ?? []).filter((f) => !NOT_AGREEMENT_INPUTS.has(f));
}
