// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The rules the plant register screens apply before they talk to the server:
// what a form draft is still missing, how a draft becomes a request body, which
// step a state offers next and where an item sits on the long-lead timeline.
// Plain functions, no React, so each one is a unit test.
//
// The server repeats every check. These only keep a reader from sending a
// form the server is certain to refuse, and name the gap beside the field.

import { parseDecimalInput, toDecimalPayloadString } from '@/shared/lib/parseDecimal';

import type {
  FeeRefundable,
  ItemInput,
  ItemStatus,
  ItServiceInput,
  LeadBasis,
  OrderStatus,
  PaperInput,
  PerformanceRow,
  PlantItem,
  QuoteInput,
  SlotInput,
  SlotStatus,
  SpareInput,
  SpareStatus,
  VendorPolicy,
} from './api';
import type { KeyText } from './labels';

/* ── Problems a draft can have ────────────────────────────────────────── */

export type Problem =
  | 'code_required'
  | 'code_invalid'
  | 'title_required'
  | 'class_required'
  | 'quantity_invalid'
  | 'vendor_reason_required'
  | 'critical_reason_required'
  | 'long_lead_reason_required'
  | 'source_required'
  | 'enquiry_date_required'
  | 'enquiry_date_in_future'
  | 'response_before_enquiry'
  | 'lead_weeks_required'
  | 'lead_weeks_range'
  | 'slot_range'
  | 'fee_invalid'
  | 'currency_invalid'
  | 'fee_currency_required'
  | 'cost_currency_required'
  | 'no_asset_reason_required'
  | 'question_required'
  | 'option_incomplete'
  | 'option_codes_unique'
  | 'score_invalid'
  | 'category_required'
  | 'kind_required'
  | 'needed_range';

export const PROBLEM: Record<Problem, KeyText> = {
  code_required: ['plant.problem.code_required', 'Give the item a code, for example PL-001.'],
  code_invalid: [
    'plant.problem.code_invalid',
    'The code may use letters, digits, dot, dash, slash and underscore, and starts with a letter or digit.',
  ],
  title_required: ['plant.problem.title_required', 'Give the item a title.'],
  class_required: ['plant.problem.class_required', 'Choose what kind of plant this is.'],
  quantity_invalid: [
    'plant.problem.quantity_invalid',
    'Quantity must be a number greater than zero, with at most three decimals.',
  ],
  vendor_reason_required: ['plant.problem.vendor_reason_required', 'A vendor-bound specification needs a reason.'],
  critical_reason_required: [
    'plant.problem.critical_reason_required',
    'Write down why the criticality differs from the class default.',
  ],
  long_lead_reason_required: [
    'plant.problem.long_lead_reason_required',
    'Write down why the long-lead classification is overridden.',
  ],
  source_required: ['plant.problem.source_required', 'Choose where the lead time comes from.'],
  enquiry_date_required: ['plant.problem.enquiry_date_required', 'A lead time needs the date it was enquired.'],
  enquiry_date_in_future: ['plant.problem.enquiry_date_in_future', 'The enquiry date cannot be in the future.'],
  response_before_enquiry: [
    'plant.problem.response_before_enquiry',
    'The response date cannot be before the enquiry date.',
  ],
  lead_weeks_required: ['plant.problem.lead_weeks_required', 'Enter the lead time in whole weeks.'],
  lead_weeks_range: ['plant.problem.lead_weeks_range', 'The shortest lead time must not exceed the longest.'],
  slot_range: ['plant.problem.slot_range', 'The slot ends before it starts.'],
  fee_invalid: [
    'plant.problem.fee_invalid',
    'The reservation fee must be an amount of zero or more, with at most two decimals.',
  ],
  fee_currency_required: ['plant.problem.fee_currency_required', 'A reservation fee needs its currency.'],
  cost_currency_required: ['plant.problem.cost_currency_required', 'An option with a cost needs its currency.'],
  no_asset_reason_required: [
    'plant.problem.no_asset_reason_required',
    'Write down why the item is handed over without a service contract.',
  ],
  currency_invalid: ['plant.problem.currency_invalid', 'Give the currency as a three-letter code, for example EUR.'],
  question_required: ['plant.problem.question_required', 'Write the question this paper decides.'],
  option_incomplete: ['plant.problem.option_incomplete', 'Every option needs a short code and a title.'],
  option_codes_unique: ['plant.problem.option_codes_unique', 'Every option needs its own code.'],
  score_invalid: [
    'plant.problem.score_invalid',
    'Scores, weights and costs must be numbers, and a cost has at most two decimals.',
  ],
  category_required: ['plant.problem.category_required', 'Choose the kind of spare.'],
  kind_required: ['plant.problem.kind_required', 'Choose the service.'],
  needed_range: ['plant.problem.needed_range', 'The service ends before it starts.'],
};

const CODE_RE = /^[A-Za-z0-9][A-Za-z0-9_.\-/]*$/;
const CURRENCY_RE = /^[A-Z]{3}$/;
const WEEKS_RE = /^\d{1,3}$/;

/** A typed decimal the server will accept, in the reader's own notation. */
export function isDecimalText(raw: string): boolean {
  return raw.trim() !== '' && parseDecimalInput(raw.trim()) !== null;
}

/**
 * The server takes three decimals on a quantity and two on money, and refuses
 * a finer figure. Trailing zeros do not count: a stored `2.0000` is two.
 */
function fits(raw: string, places: number): boolean {
  const decimals = (toDecimalPayloadString(raw).split('.')[1] ?? '').replace(/0+$/, '');
  return decimals.length <= places;
}

function positive(raw: string): boolean {
  const n = parseDecimalInput(raw.trim());
  return n !== null && n > 0 && fits(raw, 3);
}

function nonNegative(raw: string): boolean {
  const n = parseDecimalInput(raw.trim());
  return n !== null && n >= 0 && fits(raw, 2);
}

/* ── Item ─────────────────────────────────────────────────────────────── */

/** `default` follows the class or the lead time; yes and no are the reader's own call. */
export type Override = 'default' | 'yes' | 'no';

export interface ItemDraft {
  code: string;
  title: string;
  description: string;
  component_class_code: string;
  quantity: string;
  unit: string;
  tag: string;
  space_ref: string;
  performance: PerformanceRow[];
  redundancy_scheme: string;
  vendor_policy: VendorPolicy;
  vendor_bound_reason: string;
  critical: Override;
  critical_reason: string;
  need_date_fixed: string;
  maintenance_strategy: string;
  long_lead: Override;
  long_lead_override_reason: string;
  owner_user_id: string;
}

const toOverride = (value: boolean | null): Override => (value === null ? 'default' : value ? 'yes' : 'no');
const fromOverride = (value: Override): boolean | null => (value === 'default' ? null : value === 'yes');

export function emptyItemDraft(): ItemDraft {
  return {
    code: '',
    title: '',
    description: '',
    component_class_code: '',
    quantity: '1',
    unit: '',
    tag: '',
    space_ref: '',
    performance: [],
    redundancy_scheme: '',
    vendor_policy: 'neutral',
    vendor_bound_reason: '',
    critical: 'default',
    critical_reason: '',
    need_date_fixed: '',
    maintenance_strategy: '',
    long_lead: 'default',
    long_lead_override_reason: '',
    owner_user_id: '',
  };
}

export function itemDraftOf(item: PlantItem): ItemDraft {
  return {
    code: item.code,
    title: item.title,
    description: item.description,
    component_class_code: item.component_class_code,
    quantity: item.quantity,
    unit: item.unit,
    tag: item.tag,
    space_ref: item.space_ref,
    performance: item.performance.map((r) => ({ key: r.key, value: r.value ?? '', unit: r.unit ?? '' })),
    redundancy_scheme: item.redundancy_scheme,
    vendor_policy: item.vendor_policy,
    vendor_bound_reason: item.vendor_bound_reason,
    critical: toOverride(item.critical_override),
    critical_reason: item.critical_reason,
    need_date_fixed: item.need_date_fixed ?? '',
    maintenance_strategy: item.maintenance_strategy,
    long_lead: toOverride(item.long_lead_override),
    long_lead_override_reason: item.long_lead_override_reason,
    owner_user_id: item.owner_user_id ?? '',
  };
}

export function itemProblems(draft: ItemDraft, creating: boolean): Problem[] {
  const out: Problem[] = [];
  if (creating) {
    if (!draft.code.trim()) out.push('code_required');
    else if (!CODE_RE.test(draft.code.trim())) out.push('code_invalid');
  }
  if (!draft.title.trim()) out.push('title_required');
  if (!draft.component_class_code) out.push('class_required');
  if (!positive(draft.quantity)) out.push('quantity_invalid');
  if (draft.vendor_policy === 'bound' && !draft.vendor_bound_reason) out.push('vendor_reason_required');
  if (draft.critical !== 'default' && !draft.critical_reason.trim()) out.push('critical_reason_required');
  if (draft.long_lead !== 'default' && !draft.long_lead_override_reason.trim()) out.push('long_lead_reason_required');
  return out;
}

function cleanPerformance(rows: PerformanceRow[]): PerformanceRow[] {
  return rows
    .map((r) => ({ key: r.key.trim(), value: r.value.trim(), unit: r.unit.trim() }))
    .filter((r) => r.key !== '');
}

/** The whole draft as a request body, as a create sends it. */
export function toItemInput(draft: ItemDraft): ItemInput {
  return {
    code: draft.code.trim(),
    title: draft.title.trim(),
    description: draft.description.trim(),
    component_class_code: draft.component_class_code,
    quantity: toDecimalPayloadString(draft.quantity, '1'),
    unit: draft.unit.trim(),
    tag: draft.tag.trim(),
    space_ref: draft.space_ref.trim(),
    performance: cleanPerformance(draft.performance),
    redundancy_scheme: draft.redundancy_scheme,
    vendor_policy: draft.vendor_policy,
    vendor_bound_reason: draft.vendor_policy === 'bound' ? draft.vendor_bound_reason : '',
    critical_override: fromOverride(draft.critical),
    critical_reason: draft.critical === 'default' ? '' : draft.critical_reason.trim(),
    need_date_fixed: draft.need_date_fixed || null,
    maintenance_strategy: draft.maintenance_strategy,
    long_lead_override: fromOverride(draft.long_lead),
    long_lead_override_reason: draft.long_lead === 'default' ? '' : draft.long_lead_override_reason.trim(),
    owner_user_id: draft.owner_user_id || null,
  };
}

/**
 * A new item as the create sends it: nothing the reader left empty. An empty
 * redundancy or maintenance code is not "none" to the server, it is an unknown
 * code, so an untouched field must not travel at all.
 */
export function toCreateInput(draft: ItemDraft): ItemInput {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(toItemInput(draft))) {
    if (value === '' || value === null || (Array.isArray(value) && value.length === 0)) continue;
    out[key] = value;
  }
  return out as ItemInput;
}

/**
 * Only the fields an edit changed. An item past enquiry refuses any touch of
 * its specification, so sending an unchanged class back would turn a note
 * edit into a `specification_frozen` refusal. The code is never sent: it is
 * the item's identity and the update schema does not take it.
 */
export function itemChanges(original: PlantItem, draft: ItemDraft): ItemInput {
  const before: Record<string, unknown> = { ...toItemInput(itemDraftOf(original)) };
  const after: Record<string, unknown> = { ...toItemInput(draft) };
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(after)) {
    if (key === 'code') continue;
    if (JSON.stringify(after[key]) !== JSON.stringify(before[key])) out[key] = after[key];
  }
  return out as ItemInput;
}

/* ── States ───────────────────────────────────────────────────────────── */

export type ManualTarget = 'specified' | 'enquired' | 'route_set' | 'manufactured' | 'cancelled';

const NEXT_BY_HAND: Partial<Record<ItemStatus, ManualTarget>> = {
  identified: 'specified',
  specified: 'enquired',
  enquired: 'route_set',
  ordered: 'manufactured',
};

/** The one step a reader takes by hand from a state, or null when the next state is read from its source. */
export function nextManualStep(status: ItemStatus): ManualTarget | null {
  return NEXT_BY_HAND[status] ?? null;
}

/** From `route_set` on the server no longer takes a change to the critical and long-lead overrides. */
export function classificationFrozen(status: ItemStatus): boolean {
  return status !== 'identified' && status !== 'specified' && status !== 'enquired';
}

export function isClosed(status: ItemStatus): boolean {
  return status === 'handed_over' || status === 'cancelled';
}

/** States an order, a delivery or commissioning sets; "Read state from source" refreshes them. */
export function isReadFromSource(status: ItemStatus): boolean {
  return ['route_set', 'ordered', 'manufactured', 'delivered', 'installed'].includes(status);
}

const SPARE_NEXT: Partial<Record<SpareStatus, Exclude<SpareStatus, 'required' | 'waived'>>> = {
  required: 'specified',
  specified: 'delivered',
  delivered: 'handed_over',
};

export function nextSpareStep(status: SpareStatus): Exclude<SpareStatus, 'required' | 'waived'> | null {
  return SPARE_NEXT[status] ?? null;
}

export function spareIsOpen(status: SpareStatus): boolean {
  return status !== 'handed_over' && status !== 'waived';
}

export function slotIsOpen(status: SlotStatus): boolean {
  return status === 'requested' || status === 'held';
}

/* ── Lead time quote ──────────────────────────────────────────────────── */

export interface QuoteDraft {
  source: string;
  source_name: string;
  enquiry_date: string;
  response_date: string;
  lead_weeks_min: string;
  lead_weeks_max: string;
  lead_basis: LeadBasis;
  valid_until: string;
  document_ref: string;
  note: string;
  set_basis: boolean;
}

export function emptyQuoteDraft(): QuoteDraft {
  return {
    source: '',
    source_name: '',
    enquiry_date: '',
    response_date: '',
    lead_weeks_min: '',
    lead_weeks_max: '',
    lead_basis: 'from_order',
    valid_until: '',
    document_ref: '',
    note: '',
    set_basis: true,
  };
}

export function quoteProblems(draft: QuoteDraft, today: string): Problem[] {
  const out: Problem[] = [];
  if (!draft.source) out.push('source_required');
  if (!draft.enquiry_date) out.push('enquiry_date_required');
  else if (draft.enquiry_date > today) out.push('enquiry_date_in_future');
  if (draft.enquiry_date && draft.response_date && draft.response_date < draft.enquiry_date) {
    out.push('response_before_enquiry');
  }
  const min = draft.lead_weeks_min.trim();
  const max = draft.lead_weeks_max.trim() || min;
  if (!WEEKS_RE.test(min) || !WEEKS_RE.test(max)) out.push('lead_weeks_required');
  else if (Number(min) > Number(max)) out.push('lead_weeks_range');
  return out;
}

/** A single figure is a range of one: leaving the longest empty means "exactly this many weeks". */
export function toQuoteInput(draft: QuoteDraft): QuoteInput {
  const min = Number(draft.lead_weeks_min.trim());
  const max = draft.lead_weeks_max.trim() ? Number(draft.lead_weeks_max.trim()) : min;
  return {
    source: draft.source,
    source_name: draft.source_name.trim(),
    enquiry_date: draft.enquiry_date || null,
    response_date: draft.response_date || null,
    lead_weeks_min: min,
    lead_weeks_max: max,
    lead_basis: draft.lead_basis,
    valid_until: draft.valid_until || null,
    document_ref: draft.document_ref.trim(),
    note: draft.note.trim(),
    set_basis: draft.set_basis,
  };
}

/* ── Capacity reservation ─────────────────────────────────────────────── */

export interface SlotDraft {
  vendor_name: string;
  slot_from: string;
  slot_to: string;
  reservation_fee: string;
  currency: string;
  fee_refundable: FeeRefundable | '';
  fee_credited_to_order: boolean;
  convert_by_date: string;
  terms: string;
  document_ref: string;
}

export function emptySlotDraft(): SlotDraft {
  return {
    vendor_name: '',
    slot_from: '',
    slot_to: '',
    reservation_fee: '',
    currency: '',
    fee_refundable: '',
    fee_credited_to_order: false,
    convert_by_date: '',
    terms: '',
    document_ref: '',
  };
}

export function slotProblems(draft: SlotDraft): Problem[] {
  const out: Problem[] = [];
  if (draft.slot_from && draft.slot_to && draft.slot_to < draft.slot_from) out.push('slot_range');
  if (draft.reservation_fee.trim() && !nonNegative(draft.reservation_fee)) out.push('fee_invalid');
  if (draft.currency.trim() && !CURRENCY_RE.test(draft.currency.trim().toUpperCase())) out.push('currency_invalid');
  if (draft.reservation_fee.trim() && !draft.currency.trim()) out.push('fee_currency_required');
  return out;
}

/** Only what the reader filled in: the server reads an absent field as "not agreed yet". */
export function toSlotInput(draft: SlotDraft): SlotInput {
  const out: SlotInput = { fee_credited_to_order: draft.fee_credited_to_order };
  if (draft.vendor_name.trim()) out.vendor_name = draft.vendor_name.trim();
  if (draft.slot_from) out.slot_from = draft.slot_from;
  if (draft.slot_to) out.slot_to = draft.slot_to;
  if (draft.reservation_fee.trim()) out.reservation_fee = toDecimalPayloadString(draft.reservation_fee);
  if (draft.currency.trim()) out.currency = draft.currency.trim().toUpperCase();
  if (draft.fee_refundable) out.fee_refundable = draft.fee_refundable;
  if (draft.convert_by_date) out.convert_by_date = draft.convert_by_date;
  if (draft.terms.trim()) out.terms = draft.terms.trim();
  if (draft.document_ref.trim()) out.document_ref = draft.document_ref.trim();
  return out;
}

/**
 * How one field of a draft travels in an edit. `text` may be emptied, `date`
 * and `amount` are cleared with null, and a `code`, a `currency` or a
 * `quantity` cannot be emptied at all: the server takes neither null nor an
 * empty string there, so an emptied one is left as it was.
 */
type FieldKind = 'text' | 'date' | 'amount' | 'quantity' | 'code' | 'currency' | 'flag';

function wire(kind: FieldKind, value: string | boolean): string | boolean | null {
  if (typeof value === 'boolean') return value;
  const text = value.trim();
  if (text === '') return kind === 'text' ? '' : null;
  if (kind === 'amount' || kind === 'quantity') return toDecimalPayloadString(text);
  return kind === 'currency' ? text.toUpperCase() : text;
}

/**
 * Only the fields an edit changed. Sending the whole form back would touch
 * fields the reader never saw as changed, and leaving an emptied field out
 * would close the dialog as saved while the server keeps the old value.
 */
function draftChanges<D extends object>(before: D, after: D, kinds: { [K in keyof D]: FieldKind }): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(kinds) as Array<keyof D & string>) {
    const kind = kinds[key];
    const now = wire(kind, after[key] as string | boolean);
    if (now === wire(kind, before[key] as string | boolean)) continue;
    if (now === null && kind !== 'date' && kind !== 'amount') continue;
    out[key] = now;
  }
  return out;
}

const SLOT_FIELDS: { [K in keyof SlotDraft]: FieldKind } = {
  vendor_name: 'text',
  slot_from: 'date',
  slot_to: 'date',
  reservation_fee: 'amount',
  currency: 'currency',
  fee_refundable: 'code',
  fee_credited_to_order: 'flag',
  convert_by_date: 'date',
  terms: 'text',
  document_ref: 'text',
};

export function slotChanges(original: SlotDraft, draft: SlotDraft): SlotInput {
  return draftChanges(original, draft, SLOT_FIELDS) as SlotInput;
}

/* ── Decision paper ───────────────────────────────────────────────────── */

export interface OptionDraft {
  rowId: string;
  code: string;
  title: string;
  lead_weeks: string;
  cost: string;
  currency: string;
  /** Score per criterion row id. */
  scores: Record<string, string>;
  /** Links an existing option carries that this form does not edit; sent back untouched. */
  keep?: { vendor_id?: string | null; quote_id?: string | null; risk_ref?: string | null };
}

export interface CriterionDraft {
  rowId: string;
  code: string;
  title: string;
  weight: string;
}

export interface PaperDraft {
  question: string;
  options: OptionDraft[];
  criteria: CriterionDraft[];
  /** Row id of the recommended option, or empty. */
  recommendation: string;
  rationale: string;
}

/** A stable code for a criterion the reader only gave a title: "Local service" becomes `local_service`. */
export function slugCode(title: string, fallback: string): string {
  const slug = title
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return slug || fallback;
}

export function paperProblems(draft: PaperDraft): Problem[] {
  const out: Problem[] = [];
  if (!draft.question.trim()) out.push('question_required');
  if (draft.options.some((o) => !o.code.trim() || !o.title.trim())) out.push('option_incomplete');
  const codes = draft.options.map((o) => o.code.trim()).filter(Boolean);
  if (new Set(codes).size !== codes.length) out.push('option_codes_unique');
  const numbers = [
    ...draft.criteria.map((c) => c.weight),
    ...draft.options.flatMap((o) => [o.cost, ...draft.criteria.map((c) => o.scores[c.rowId] ?? '')]),
  ].filter((v) => v.trim() !== '');
  const weeksBad = draft.options.some((o) => o.lead_weeks.trim() !== '' && !WEEKS_RE.test(o.lead_weeks.trim()));
  const currencyBad = draft.options.some(
    (o) => o.currency.trim() !== '' && !CURRENCY_RE.test(o.currency.trim().toUpperCase()),
  );
  const costBad = draft.options.some((o) => o.cost.trim() !== '' && !nonNegative(o.cost));
  if (weeksBad || costBad || numbers.some((v) => !isDecimalText(v))) out.push('score_invalid');
  if (currencyBad) out.push('currency_invalid');
  if (draft.options.some((o) => o.cost.trim() !== '' && !o.currency.trim())) out.push('cost_currency_required');
  return out;
}

export function toPaperInput(draft: PaperDraft): PaperInput {
  const criteria = draft.criteria
    .filter((c) => c.title.trim() || c.code.trim())
    .map((c, i) => ({ rowId: c.rowId, code: c.code.trim() || slugCode(c.title, `criterion_${i + 1}`), title: c.title.trim(), weight: c.weight }));
  const recommended = draft.options.find((o) => o.rowId === draft.recommendation);
  return {
    question: draft.question.trim(),
    criteria: criteria.map((c) => ({ code: c.code, title: c.title, weight: toDecimalPayloadString(c.weight, '1') })),
    options: draft.options.map((o) => {
      const scores: Record<string, string> = {};
      for (const c of criteria) {
        const raw = o.scores[c.rowId] ?? '';
        if (raw.trim()) scores[c.code] = toDecimalPayloadString(raw);
      }
      return {
        ...o.keep,
        code: o.code.trim(),
        title: o.title.trim(),
        lead_weeks: o.lead_weeks.trim() ? Number(o.lead_weeks.trim()) : null,
        cost: o.cost.trim() ? toDecimalPayloadString(o.cost) : null,
        currency: o.currency.trim() ? o.currency.trim().toUpperCase() : null,
        scores,
      };
    }),
    recommendation: recommended ? recommended.code.trim() : '',
    rationale: draft.rationale.trim(),
  };
}

/* ── Spares and IT services ───────────────────────────────────────────── */

export interface SpareDraft {
  category: string;
  description: string;
  quantity: string;
  unit: string;
  supply_by: string;
  handover_target: string;
}

export function spareProblems(draft: SpareDraft): Problem[] {
  const out: Problem[] = [];
  if (!draft.category) out.push('category_required');
  if (!positive(draft.quantity)) out.push('quantity_invalid');
  return out;
}

export function toSpareInput(draft: SpareDraft): SpareInput {
  const out: SpareInput = {
    category: draft.category,
    description: draft.description.trim(),
    quantity: toDecimalPayloadString(draft.quantity, '1'),
    unit: draft.unit.trim(),
    handover_target: draft.handover_target.trim(),
  };
  if (draft.supply_by) out.supply_by = draft.supply_by;
  return out;
}

const SPARE_FIELDS: { [K in keyof SpareDraft]: FieldKind } = {
  category: 'code',
  description: 'text',
  quantity: 'quantity',
  unit: 'text',
  supply_by: 'code',
  handover_target: 'text',
};

export function spareChanges(original: SpareDraft, draft: SpareDraft): SpareInput {
  return draftChanges(original, draft, SPARE_FIELDS) as SpareInput;
}

export interface ItServiceDraft {
  kind: string;
  description: string;
  responsible_party: string;
  needed_from: string;
  needed_until: string;
}

export function itServiceProblems(draft: ItServiceDraft): Problem[] {
  const out: Problem[] = [];
  if (!draft.kind) out.push('kind_required');
  if (draft.needed_from && draft.needed_until && draft.needed_until < draft.needed_from) out.push('needed_range');
  return out;
}

export function toItServiceInput(draft: ItServiceDraft): ItServiceInput {
  const out: ItServiceInput = { kind: draft.kind, description: draft.description.trim() };
  if (draft.responsible_party) out.responsible_party = draft.responsible_party;
  if (draft.needed_from) out.needed_from = draft.needed_from;
  if (draft.needed_until) out.needed_until = draft.needed_until;
  return out;
}

const IT_SERVICE_FIELDS: { [K in keyof ItServiceDraft]: FieldKind } = {
  kind: 'code',
  description: 'text',
  responsible_party: 'code',
  needed_from: 'date',
  needed_until: 'date',
};

export function itServiceChanges(original: ItServiceDraft, draft: ItServiceDraft): ItServiceInput {
  return draftChanges(original, draft, IT_SERVICE_FIELDS) as ItServiceInput;
}

/* ── Register filters and the timeline ────────────────────────────────── */

export type RegisterFilter = 'all' | 'long_lead' | 'critical' | 'overdue';

export function filterItems(items: PlantItem[], filter: RegisterFilter): PlantItem[] {
  if (filter === 'long_lead') return items.filter((i) => i.long_lead);
  if (filter === 'critical') return items.filter((i) => i.critical);
  if (filter === 'overdue') return items.filter((i) => i.order_status === 'overdue');
  return items;
}

export function filterCounts(items: PlantItem[]): Record<RegisterFilter, number> {
  return {
    all: items.length,
    long_lead: filterItems(items, 'long_lead').length,
    critical: filterItems(items, 'critical').length,
    overdue: filterItems(items, 'overdue').length,
  };
}

export type Tone = 'neutral' | 'blue' | 'purple' | 'success' | 'warning' | 'error';

export const ORDER_TONE: Record<OrderStatus, Tone> = { ok: 'success', due_soon: 'warning', overdue: 'error' };

/** Whether the order date still matters: once ordered, the float is history. */
export function orderDateOpen(item: Pick<PlantItem, 'status'>): boolean {
  return ['identified', 'specified', 'enquired', 'route_set'].includes(item.status);
}

const DAY_MS = 86_400_000;

function dayNumber(iso: string): number {
  return Math.round(Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / DAY_MS);
}

export interface TimelineRow {
  item: PlantItem;
  /** Percent positions along the shared axis; null when the item has no such date. */
  orderAt: number | null;
  needAt: number | null;
}

export interface Timeline {
  start: string;
  end: string;
  todayAt: number;
  rows: TimelineRow[];
}

/**
 * Place every long-lead item on one axis from the earliest date in play
 * (today included) to the latest need date, so the reader compares bars and
 * not numbers. An item without a need date keeps its row and gets no bar.
 */
export function buildTimeline(items: PlantItem[], today: string): Timeline {
  const days = [dayNumber(today)];
  for (const i of items) {
    if (i.latest_order_date) days.push(dayNumber(i.latest_order_date));
    if (i.need_date) days.push(dayNumber(i.need_date));
  }
  const first = Math.min(...days);
  const last = Math.max(...days);
  const span = Math.max(last - first, 1);
  const at = (iso: string | null): number | null =>
    iso ? Math.round(((dayNumber(iso) - first) / span) * 1000) / 10 : null;
  const iso = (day: number) => new Date(day * DAY_MS).toISOString().slice(0, 10);
  return {
    start: iso(first),
    end: iso(last),
    todayAt: at(today) ?? 0,
    rows: items.map((item) => ({ item, orderAt: at(item.latest_order_date), needAt: at(item.need_date) })),
  };
}
