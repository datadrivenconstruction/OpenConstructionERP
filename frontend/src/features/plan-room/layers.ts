// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Layer catalogue and colour helpers for the Plan Room.
 *
 * Every overlay source is its own toggleable layer. Each layer has a stable
 * swatch colour so the legend and the marks on the sheet read as the same
 * layer at a glance. Pin colours additionally encode the punch item's priority
 * (the field the payload carries) so an urgent snag stands out.
 */

import type { OverlayPin } from './api';

/** The five overlay sources composited onto a page, in draw order. */
export type LayerKey = 'punch' | 'plan' | 'markups' | 'measurements' | 'photos';

export interface LayerMeta {
  key: LayerKey;
  /** i18n key + English default for the legend label. */
  labelKey: string;
  defaultLabel: string;
  /** Legend swatch / default mark colour. */
  color: string;
}

/**
 * Layer order and identity. Pins sit on top (they are the interactive marks);
 * photos are last because they render in a side gallery, not on the sheet.
 */
export const LAYERS: LayerMeta[] = [
  { key: 'punch', labelKey: 'plan_room.layer_punch', defaultLabel: 'Punch pins', color: '#ef4444' },
  { key: 'plan', labelKey: 'plan_room.layer_plan', defaultLabel: 'Plan pins', color: '#2563eb' },
  { key: 'markups', labelKey: 'plan_room.layer_markups', defaultLabel: 'Markups', color: '#a855f7' },
  {
    key: 'measurements',
    labelKey: 'plan_room.layer_measurements',
    defaultLabel: 'Measurements',
    color: '#10b981',
  },
  { key: 'photos', labelKey: 'plan_room.layer_photos', defaultLabel: 'Photos', color: '#f59e0b' },
];

/** All layers start visible. */
export function allLayersVisible(): Record<LayerKey, boolean> {
  return { punch: true, plan: true, markups: true, measurements: true, photos: true };
}

/** Fixed swatch colour for the "plan pin" mark (matches the legend). */
export const PLAN_PIN_COLOR = '#2563eb';

/** Punch-pin dot colour by priority so urgent snags read at a glance; mirrors
 *  the punch pin board's palette. Unknown / missing priority falls back to the
 *  punch layer colour. */
const PUNCH_PRIORITY_COLOR: Record<string, string> = {
  low: '#6b7280',
  medium: '#eab308',
  high: '#f97316',
  critical: '#ef4444',
};

/** Resolve the dot colour for a pin from its kind + priority. */
export function pinColor(pin: OverlayPin): string {
  if (pin.kind === 'plan') return PLAN_PIN_COLOR;
  return (pin.priority && PUNCH_PRIORITY_COLOR[pin.priority]) || '#ef4444';
}

/** Map a pin / markup status to a shared Badge variant. */
export function statusBadgeVariant(
  status: string | null,
): 'neutral' | 'blue' | 'success' | 'warning' | 'error' {
  if (!status) return 'neutral';
  const s = status.toLowerCase();
  if (['closed', 'verified', 'resolved', 'approved', 'done'].includes(s)) return 'success';
  if (['open', 'rejected', 'failed'].includes(s)) return 'error';
  if (['in_progress', 'assigned', 'pending', 'review'].includes(s)) return 'warning';
  return 'blue';
}
