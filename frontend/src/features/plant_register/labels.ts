// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the plant register shows for a code: the closed vocabularies
// (item state, order status, slot, paper, spare, IT service) and the names of
// catalogue entries. The vocabularies are written as key maps rather than
// built from the code at runtime, so the key test can enumerate them and a
// translator can find every key by grep.

import type {
  CatalogueEntry,
  DateBasis,
  FeeRefundable,
  ItemClass,
  ItemStatus,
  ItStatus,
  LeadBasis,
  OrderStatus,
  PaperStatus,
  PlantCatalogue,
  PlantViolation,
  SlotStatus,
  SpareStatus,
  VendorBoundReason,
  VendorPolicy,
} from './api';
import { ERROR_TEXT } from './errors';

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];

export type TFn = (key: string, options?: Record<string, unknown>) => string;

export interface LabelContext {
  t: TFn;
  language: string;
  exists: (key: string) => boolean;
}

export const ITEM_STATE: Record<ItemStatus, KeyText> = {
  identified: ['plant.state.identified', 'Identified'],
  specified: ['plant.state.specified', 'Specified'],
  enquired: ['plant.state.enquired', 'Enquired'],
  route_set: ['plant.state.route_set', 'Route set'],
  ordered: ['plant.state.ordered', 'Ordered'],
  manufactured: ['plant.state.manufactured', 'Manufactured'],
  delivered: ['plant.state.delivered', 'Delivered'],
  installed: ['plant.state.installed', 'Installed'],
  commissioned: ['plant.state.commissioned', 'Commissioned'],
  handed_over: ['plant.state.handed_over', 'Handed over'],
  cancelled: ['plant.state.cancelled', 'Cancelled'],
};

/** What the button that moves an item to a state says. */
export const ITEM_STEP_ACTION: Record<'specified' | 'enquired' | 'route_set' | 'manufactured' | 'cancelled', KeyText> = {
  specified: ['plant.item.step.specified', 'Mark as specified'],
  enquired: ['plant.item.step.enquired', 'Mark as enquired'],
  route_set: ['plant.item.step.route_set', 'Confirm the route'],
  manufactured: ['plant.item.step.manufactured', 'Record factory acceptance'],
  cancelled: ['plant.item.step.cancelled', 'Cancel item'],
};

export const ITEM_CLASS: Record<ItemClass, KeyText> = {
  main_component: ['plant.item_class.main_component', 'Main component'],
  user_equipment: ['plant.item_class.user_equipment', 'User equipment'],
  operating_equipment: ['plant.item_class.operating_equipment', 'Operating equipment'],
};

export const ORDER_STATUS: Record<OrderStatus, KeyText> = {
  ok: ['plant.order_status.ok', 'On track'],
  due_soon: ['plant.order_status.due_soon', 'Order soon'],
  overdue: ['plant.order_status.overdue', 'Order overdue'],
};

export const DATE_BASIS: Record<DateBasis, KeyText> = {
  activity_late_start: ['plant.date_basis.activity_late_start', 'Activity late start'],
  activity_start: ['plant.date_basis.activity_start', 'Activity start'],
  fixed: ['plant.date_basis.fixed', 'Fixed date'],
  none: ['plant.date_basis.none', 'No need date'],
};

export const LEAD_BASIS: Record<LeadBasis, KeyText> = {
  from_order: ['plant.lead_basis.from_order', 'From order'],
  from_approved_drawings: ['plant.lead_basis.from_approved_drawings', 'From approved drawings'],
  from_down_payment: ['plant.lead_basis.from_down_payment', 'From down payment'],
};

export const VENDOR_POLICY: Record<VendorPolicy, KeyText> = {
  neutral: ['plant.vendor_policy.neutral', 'Vendor neutral'],
  bound: ['plant.vendor_policy.bound', 'Vendor bound'],
};

export const VENDOR_REASON: Record<VendorBoundReason, KeyText> = {
  standardisation: ['plant.vendor_reason.standardisation', 'Standardisation'],
  existing_estate: ['plant.vendor_reason.existing_estate', 'Existing estate'],
  warranty: ['plant.vendor_reason.warranty', 'Warranty'],
  sole_source: ['plant.vendor_reason.sole_source', 'Sole source'],
};

export const SLOT_STATE: Record<SlotStatus, KeyText> = {
  requested: ['plant.slot_state.requested', 'Requested'],
  held: ['plant.slot_state.held', 'Held'],
  converted_to_order: ['plant.slot_state.converted_to_order', 'Converted to order'],
  released: ['plant.slot_state.released', 'Released'],
  expired: ['plant.slot_state.expired', 'Expired'],
};

export const PAPER_STATE: Record<PaperStatus, KeyText> = {
  draft: ['plant.paper_state.draft', 'Draft'],
  submitted: ['plant.paper_state.submitted', 'Submitted'],
  approved: ['plant.paper_state.approved', 'Approved'],
  rejected: ['plant.paper_state.rejected', 'Rejected'],
};

export const SPARE_STATE: Record<SpareStatus, KeyText> = {
  required: ['plant.spare_state.required', 'Required'],
  specified: ['plant.spare_state.specified', 'Specified'],
  delivered: ['plant.spare_state.delivered', 'Delivered'],
  handed_over: ['plant.spare_state.handed_over', 'Handed over'],
  waived: ['plant.spare_state.waived', 'Waived'],
};

/** What the button that moves a spare line to a state says. */
export const SPARE_STEP_ACTION: Record<Exclude<SpareStatus, 'required'>, KeyText> = {
  specified: ['plant.spare.step.specified', 'Mark as specified'],
  delivered: ['plant.spare.step.delivered', 'Mark as delivered'],
  handed_over: ['plant.spare.step.handed_over', 'Mark as handed over'],
  waived: ['plant.spare.step.waived', 'Waive'],
};

export const IT_STATE: Record<ItStatus, KeyText> = {
  planned: ['plant.it_state.planned', 'Planned'],
  provisioned: ['plant.it_state.provisioned', 'Provisioned'],
  retired: ['plant.it_state.retired', 'Retired'],
};

export const FEE_REFUNDABLE: Record<FeeRefundable, KeyText> = {
  none: ['plant.fee_refundable.none', 'Not refundable'],
  partial: ['plant.fee_refundable.partial', 'Partly refundable'],
  full: ['plant.fee_refundable.full', 'Fully refundable'],
};

export const FINDING_SEVERITY: Record<'error' | 'warning' | 'info', KeyText> = {
  error: ['plant.severity.error', 'Must fix'],
  warning: ['plant.severity.warning', 'Check'],
  info: ['plant.severity.info', 'Note'],
};

/** Findings the server derives on an item's vendor policy that are not refusal codes. */
export const VENDOR_FINDING: Record<string, KeyText> = {
  vendor_bound_needs_reason: ['plant.errors.vendor_bound_needs_reason', 'A vendor-bound specification needs a reason.'],
  neutral_spec_names_vendor: [
    'plant.finding.neutral_spec_names_vendor',
    'The specification is vendor neutral but names a vendor.',
  ],
};

/** Every vocabulary map, for the test that proves each key resolves in en and de. */
export const ALL_KEY_MAPS: Record<string, Record<string, KeyText>> = {
  ITEM_STATE,
  ITEM_STEP_ACTION,
  ITEM_CLASS,
  ORDER_STATUS,
  DATE_BASIS,
  LEAD_BASIS,
  VENDOR_POLICY,
  VENDOR_REASON,
  SLOT_STATE,
  PAPER_STATE,
  SPARE_STATE,
  SPARE_STEP_ACTION,
  IT_STATE,
  FEE_REFUNDABLE,
  FINDING_SEVERITY,
  VENDOR_FINDING,
};

/**
 * A code written for a reader: `cost_finance` becomes "Cost finance".
 *
 * The last resort when neither the catalogue nor the locale names the item.
 * It is never a raw key, which is what a demo must not show.
 */
export function humanizeCode(code: string): string {
  const words = code.replace(/[_-]+/g, ' ').trim();
  if (!words) return '';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Render a vocabulary entry. An unknown code shows humanised rather than as a raw key. */
export function vocab<T extends string>(t: TFn, map: Record<T, KeyText>, code: T | '' | null | undefined): string {
  if (!code) return '';
  const entry = map[code as T];
  if (!entry) return humanizeCode(code);
  return t(entry[0], { defaultValue: entry[1] });
}

/** The catalogue lists a reader meets, and the key segment each one's entries are named under. */
export const CATALOGUE_GROUPS = {
  component_classes: 'class',
  redundancy_schemes: 'redundancy',
  procurement_routes: 'route',
  lead_time_sources: 'source',
  spare_categories: 'spare',
  maintenance_strategies: 'maintenance',
  delivery_limit_steps: 'step',
  site_plant_kinds: 'site_plant',
  it_service_kinds: 'it_service',
  parties: 'party',
} as const;

export type CatalogueGroup = keyof typeof CATALOGUE_GROUPS;

function fromEntry(entry: CatalogueEntry | undefined, ctx: LabelContext): string {
  if (!entry) return '';
  if (entry.name_key && ctx.exists(entry.name_key)) return ctx.t(entry.name_key);
  if (entry.labels) {
    const lang = ctx.language.split('-')[0] ?? 'en';
    return entry.labels[ctx.language] ?? entry.labels[lang] ?? entry.labels.en ?? Object.values(entry.labels)[0] ?? '';
  }
  return '';
}

/**
 * The name of a catalogue entry: what the pinned catalogue says first (its
 * message key, or a tenant catalogue's own texts), then the shipped key for
 * the code, then the code itself made readable.
 */
export function catalogueName(
  ctx: LabelContext,
  catalogue: PlantCatalogue | null | undefined,
  group: CatalogueGroup,
  code: string | null | undefined,
): string {
  if (!code) return '';
  const entries = (catalogue?.[group] ?? []) as CatalogueEntry[];
  const named = fromEntry(entries.find((e) => e.code === code), ctx);
  if (named) return named;
  const key = ['plant', 'catalogue', CATALOGUE_GROUPS[group], code.toLowerCase()].join('.');
  if (ctx.exists(key)) return ctx.t(key);
  // Redundancy codes are written the way engineers write them (N+1, 2N).
  return group === 'redundancy_schemes' ? code : humanizeCode(code);
}

/** Where an item's lead time comes from: a quote source, the catalogue default, or nothing yet. */
export function leadSourceName(ctx: LabelContext, catalogue: PlantCatalogue | null | undefined, code: string): string {
  return catalogueName(ctx, catalogue, 'lead_time_sources', code);
}

/** The sentence for a refusal or blocker code, translated when the locale has it. */
export function errorText(t: TFn, code: string, serverMessage?: string | null): string {
  const english = ERROR_TEXT[code] ?? serverMessage ?? humanizeCode(code);
  return t(['plant', 'errors', code].join('.'), { defaultValue: english });
}

/** One blocking rule as a sentence; the server's own reason follows when it adds something. */
export function violationText(t: TFn, violation: PlantViolation): string {
  return errorText(t, violation.code, violation.message);
}
