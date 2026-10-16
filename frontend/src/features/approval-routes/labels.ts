// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Shared label helpers for the Approval Routes feature. Target kinds are
// raw snake_case on the wire (markup, change_order, purchase_order); the
// UI must show them localised and humanised ("Change order", "Purchase
// order") rather than verbatim.

import type { TFunction } from 'i18next';

// English fallbacks for the computed `approvalRoutes.kind_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const APPROVALROUTES_KIND_LABELS: Record<string, string> = {
  markup: 'Markup', submittal: 'Submittal', change_order: 'Change order', rfi: 'RFI', contract: 'Contract',
  variation: 'Variation', invoice: 'Invoice', purchase_order: 'Purchase order',
  qms_hold_point: 'QMS hold point', interface: 'Interface agreement'
};


/** Humanise a raw snake_case kind into Title-ish prose:
 *  ``change_order`` → ``Change order``. */
function prettify(kind: string): string {
  const spaced = kind.replace(/_/g, ' ').trim();
  if (!spaced) return kind;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Localised, humanised label for a target kind. Looks up
 *  ``approvalRoutes.kind_<kind>`` and falls back to the prettified form. */
export function kindLabel(t: TFunction, kind: string): string {
  return t(`approvalRoutes.kind_${kind}`, { defaultValue: APPROVALROUTES_KIND_LABELS[kind] ?? prettify(kind) });
}
