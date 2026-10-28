// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the commitment screens show for a code: item states, commitment
// types, tiers, document kinds, preconditions and refusals. The closed
// vocabularies are written as key maps rather than built from the code at
// runtime, so the key test can enumerate them and a translator can find every
// key by grep. Tiers, types and flags are catalogue data: the schedule names
// them, and the locale or the code itself is the fallback.

import type {
  CommitmentLabel,
  DateBasis,
  LeadTimeSource,
  Enforcement,
  FxPolicy,
  ItemStatus,
  LinkKind,
  PlannedSource,
  PreconditionKind,
  ReleaseOutcome,
  ReleasePurpose,
  RouteReport,
  Transferable,
} from './api';

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];

export type TFn = (key: string, options?: Record<string, unknown>) => string;

export interface LabelContext {
  t: TFn;
  language: string;
  exists: (key: string) => boolean;
}

export const ITEM_STATUS: Record<ItemStatus, KeyText> = {
  planned: ['commitment.status.planned', 'Planned'],
  release_requested: ['commitment.status.release_requested', 'Release requested'],
  released: ['commitment.status.released', 'Released'],
  partially_released: ['commitment.status.partially_released', 'Partially released'],
  committed: ['commitment.status.committed', 'Committed'],
  closed: ['commitment.status.closed', 'Closed'],
  re_release_required: ['commitment.status.re_release_required', 'Re-release required'],
  on_hold: ['commitment.status.on_hold', 'On hold'],
  aborted: ['commitment.status.aborted', 'Aborted'],
  transferred: ['commitment.status.transferred', 'Transferred'],
};

export const ENFORCEMENT: Record<Enforcement, KeyText> = {
  off: ['commitment.enforcement.off', 'Register only'],
  warn: ['commitment.enforcement.warn', 'Warn'],
  block: ['commitment.enforcement.block', 'Block'],
};

export const ENFORCEMENT_HINT: Record<Enforcement, KeyText> = {
  off: [
    'commitment.enforcement_hint.off',
    'The matrix is a register. Awards and contract signing are not checked against it.',
  ],
  warn: [
    'commitment.enforcement_hint.warn',
    'An award or signing above the released amount goes through and is written to the audit log.',
  ],
  block: [
    'commitment.enforcement_hint.block',
    'An award or signing above the released amount is refused until the release is granted.',
  ],
};

export const FX_POLICY: Record<FxPolicy, KeyText> = {
  fx_service_rate_set: ['commitment.fx_policy.fx_service_rate_set', 'Exchange rate register'],
  project_rates: ['commitment.fx_policy.project_rates', 'Rates set on the project'],
};

export const LINK_KIND: Record<LinkKind, KeyText> = {
  contract: ['commitment.link.contract', 'Contract'],
  contract_line: ['commitment.link.contract_line', 'Contract line'],
  purchase_order: ['commitment.link.purchase_order', 'Purchase order'],
  change_order: ['commitment.link.change_order', 'Change order'],
  variation_order: ['commitment.link.variation_order', 'Variation order'],
  tender_package: ['commitment.link.tender_package', 'Tender package'],
  bid_package: ['commitment.link.bid_package', 'Bid package'],
  rfq: ['commitment.link.rfq', 'Request for quotation'],
};

export const PRECONDITION_KIND: Record<PreconditionKind, KeyText> = {
  manual: ['commitment.precondition.manual', 'Manual'],
  gate_decided: ['commitment.precondition.gate_decided', 'Gate decided'],
  frame_document_binding: ['commitment.precondition.frame_document_binding', 'Frame document binding'],
  funding_approved: ['commitment.precondition.funding_approved', 'Funding approved'],
  permit: ['commitment.precondition.permit', 'Permit'],
  budget_available: ['commitment.precondition.budget_available', 'Budget available'],
  public_commitment_appropriation: [
    'commitment.precondition.public_commitment_appropriation',
    'Commitment appropriation',
  ],
};

export const RELEASE_OUTCOME: Record<ReleaseOutcome, KeyText> = {
  pending: ['commitment.release.outcome.pending', 'Pending'],
  released: ['commitment.release.outcome.released', 'Released'],
  rejected: ['commitment.release.outcome.rejected', 'Rejected'],
  withdrawn: ['commitment.release.outcome.withdrawn', 'Withdrawn'],
  aborted: ['commitment.release.outcome.aborted', 'Abort decided'],
};

/** What a request in the history asked for. */
export const RELEASE_PURPOSE: Record<ReleasePurpose, KeyText> = {
  release: ['commitment.release.purpose.release', 'Release'],
  abort: ['commitment.release.purpose.abort', 'Abort'],
};

/** A rationale the server wrote itself when it closed a request, stored as a code. */
export const CODED_RATIONALE: Record<string, KeyText> = {
  four_eyes_violation: [
    'commitment.history.rationale.four_eyes_violation',
    'Closed by the system: the approval came from somebody four eyes bars from deciding',
  ],
  decider_not_tier_holder: [
    'commitment.history.rationale.decider_not_tier_holder',
    'Closed by the system: the approval did not come from a holder of the required tier',
  ],
  cancelled: ['commitment.history.rationale.cancelled', 'The approval was cancelled'],
};

/** The rationale of a decision: the words of a coded one, otherwise what the decider wrote. */
export function rationaleText(t: TFn, rationale: string): string {
  const coded = CODED_RATIONALE[rationale];
  return coded ? t(coded[0], { defaultValue: coded[1] }) : rationale;
}

/** What is left to do by hand with a linked document once an abort was decided. */
export const ABORT_FOLLOW_UP: Record<string, KeyText> = {
  terminate: ['commitment.abort.follow_up.terminate', 'Terminate this contract in the contracts module'],
  cancel: ['commitment.abort.follow_up.cancel', 'Cancel this order in procurement'],
};

export const DATE_BASIS: Record<DateBasis, KeyText> = {
  fixed: ['commitment.date_basis.fixed', 'Fixed date'],
  late_start: ['commitment.date_basis.late_start', 'From the late start of the activity'],
  start_date: ['commitment.date_basis.start_date', 'From the planned start (no critical path run yet)'],
  plant_item: ['commitment.date_basis.plant_item', 'From the latest order date of the plant item'],
  none: ['commitment.date_basis.none', 'No date to compute from'],
};

/** Whose lead time is in force on an item. A linked plant item is named by its code where one is known. */
export const LEAD_TIME_SOURCE: Record<LeadTimeSource, KeyText> = {
  plant_item: ['commitment.lead_time_source.plant_item', 'From the linked plant item'],
  item: ['commitment.lead_time_source.item', 'Entered on this item'],
  requisition: ['commitment.lead_time_source.requisition', 'From the linked requisition'],
};

export const TRANSFERABLE: Record<Transferable, KeyText> = {
  no: ['commitment.transferable.no', 'Not transferable'],
  to_project: ['commitment.transferable.to_project', 'Transferable to another project'],
  resale: ['commitment.transferable.resale', 'Resale'],
};

export const FX_SOURCE: Record<string, KeyText> = {
  fx_rate_set: ['commitment.fx_source.fx_rate_set', 'exchange rate register'],
  project_rates: ['commitment.fx_source.project_rates', 'project rates'],
  same_currency: ['commitment.fx_source.same_currency', 'same currency'],
};

export const PLANNED_SOURCE: Record<PlannedSource, KeyText> = {
  manual: ['commitment.planned_source.manual', 'Estimate entered here'],
  budget_line: ['commitment.planned_source.budget_line', 'Budget line'],
  cost_line: ['commitment.planned_source.cost_line', 'Cost line'],
  boq_position: ['commitment.planned_source.boq_position', 'Bill of quantities position'],
};

export const ROUTE_REPORT: Record<RouteReport, KeyText> = {
  created: ['commitment.setup.route_report.created', 'Route created'],
  replaced: ['commitment.setup.route_report.replaced', 'Route replaced'],
  unchanged: ['commitment.setup.route_report.unchanged', 'Route unchanged'],
  edited: ['commitment.setup.route_report.edited', 'Edited by hand, kept as it is'],
  unfilled: ['commitment.setup.route_report.unfilled', 'Nobody assigned yet, no route'],
  pinned: ['commitment.setup.route_report.pinned', 'Chosen by hand, kept as it is'],
};

/** Why the residual loss of an item is unknown. */
export const EXPOSURE_REASON: Record<string, KeyText> = {
  abort_terms_missing: ['commitment.exposure.unknown', 'Unknown: abort terms missing'],
  fx_rate_missing: ['commitment.exposure.reason.fx_rate_missing', 'Unknown: an exchange rate is missing'],
};

/** How the cancellation charge of an item was worked out, line by line. */
export const EXPOSURE_LINE: Record<string, KeyText> = {
  paid: ['commitment.exposure.line.paid', 'Paid'],
  invoiced_unpaid: ['commitment.exposure.line.invoiced_unpaid', 'Invoiced, not yet paid'],
  certified_not_invoiced: ['commitment.exposure.line.certified_not_invoiced', 'Certified, not yet invoiced'],
  received_not_invoiced: ['commitment.exposure.line.received_not_invoiced', 'Goods received, not yet invoiced'],
  schedule_milestone: ['commitment.exposure.line.schedule_milestone', 'Cancellation step reached'],
  unperformed_less_saved: ['commitment.exposure.line.unperformed_less_saved', 'Work not done, less saved cost'],
  presumed_pct_of_unperformed: [
    'commitment.exposure.line.presumed_pct_of_unperformed',
    'Presumed share of the work not done',
  ],
  fee_on_unperformed: ['commitment.exposure.line.fee_on_unperformed', 'Fee on the work not done'],
  profit_on_performed: ['commitment.exposure.line.profit_on_performed', 'Profit on the work done'],
};

/** Why the guard would warn about or refuse a new amount on a document, in the words of the check panel. */
export const CHECK_REASON: Record<string, KeyText> = {
  commitment_not_released: [
    'commitment.check.reason.commitment_not_released',
    'With this amount the item would bind more than was released for it.',
  ],
  release_expired: [
    'commitment.check.reason.release_expired',
    'The amount would fit what was released, but that release has passed its validity date. Request a new release first.',
  ],
  fx_rate_missing: [
    'commitment.check.reason.fx_rate_missing',
    'There is no exchange rate from this currency to the currency of the matrix, so the amount cannot be judged.',
  ],
  commitment_not_in_matrix: [
    'commitment.check.reason.commitment_not_in_matrix',
    'No item of the matrix counts this document, and this project wants every document on an item.',
  ],
};

/** What a linked document's row says about how it was counted. The code is the part before the first colon. */
export const LINK_NOTE: Record<string, KeyText> = {
  provenance_only: ['commitment.link_note.provenance_only', 'Shows where the award came from. Not counted as committed.'],
  drawdown_not_wired: ['commitment.link_note.drawdown_not_wired', 'Not counted as committed.'],
  net_of: ['commitment.link_note.net_of', 'Counted net of a linked document that is part of it.'],
  currency_mismatch_not_netted: [
    'commitment.link_note.currency_mismatch_not_netted',
    'A linked part is in another currency and was not netted off.',
  ],
  contract_header_value: ['commitment.link_note.contract_header_value', 'Counted with the contract sum, changes included.'],
  inside_contract_value: [
    'commitment.link_note.inside_contract_value',
    'Already inside the sum of its contract. Not counted a second time.',
  ],
  contract_terminated: ['commitment.link_note.contract_terminated', 'Its contract was terminated.'],
  mirror_counted_once: ['commitment.link_note.mirror_counted_once', 'The same award is linked twice and counted once.'],
  award_pair_counted_above_contract: [
    'commitment.link_note.award_pair_counted_above_contract',
    'Counted on top of the contract it belongs to.',
  ],
};

/** Every vocabulary map, for the test that proves each key resolves in en and de. */
export const ALL_KEY_MAPS: Record<string, Record<string, KeyText>> = {
  ITEM_STATUS,
  ENFORCEMENT,
  ENFORCEMENT_HINT,
  FX_POLICY,
  LINK_KIND,
  PRECONDITION_KIND,
  RELEASE_OUTCOME,
  RELEASE_PURPOSE,
  ABORT_FOLLOW_UP,
  CODED_RATIONALE,
  DATE_BASIS,
  LEAD_TIME_SOURCE,
  TRANSFERABLE,
  FX_SOURCE,
  PLANNED_SOURCE,
  ROUTE_REPORT,
  EXPOSURE_REASON,
  EXPOSURE_LINE,
  LINK_NOTE,
  CHECK_REASON,
};

/**
 * A catalogue code written for a reader: `project_manager` becomes "Project manager".
 *
 * The last resort when neither the API nor the locale names the item. It is
 * never a raw key, which is what a demo must not show.
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

function fromLabel(label: CommitmentLabel | null | undefined, ctx: LabelContext): string {
  if (!label) return '';
  if (label.key && ctx.exists(label.key)) return ctx.t(label.key);
  if (label.text) {
    const lang = ctx.language.split('-')[0] ?? 'en';
    return label.text[ctx.language] ?? label.text[lang] ?? label.text.en ?? Object.values(label.text)[0] ?? '';
  }
  return '';
}

export type CatalogueCodeKind = 'tier' | 'type' | 'flag';

/**
 * The name of a tier, commitment type or flag: the label the schedule sent,
 * then the locale's own key for the code, then the code made readable.
 */
export function codeName(
  ctx: LabelContext,
  kind: CatalogueCodeKind,
  code: string | null | undefined,
  label?: CommitmentLabel | null,
): string {
  if (!code) return '';
  const fromApi = fromLabel(label, ctx);
  if (fromApi) return fromApi;
  const key = ['commitment', kind, code].join('.');
  if (ctx.exists(key)) return ctx.t(key);
  return humanizeCode(code);
}

/** The name of a schedule or abort basis from the catalogue list. */
export function catalogueName(ctx: LabelContext, id: string, label?: CommitmentLabel | null): string {
  const fromApi = fromLabel(label, ctx);
  if (fromApi) return fromApi;
  const key = ['commitment', 'catalogue', id, 'name'].join('.');
  if (ctx.exists(key)) return ctx.t(key);
  return humanizeCode(id);
}

/** The name of a record another module owns: the label the server sent, then its code made readable. */
export function codeLabel(ctx: LabelContext, code: string, label?: CommitmentLabel | null): string {
  return fromLabel(label, ctx) || humanizeCode(code);
}

/**
 * The English of every refusal code the backend sends, as
 * `commitment.errors.<code>`. Mirrors the module's `messages/en.json`, so a
 * refusal renders a sentence even before the locale carries the key.
 */
export const ERROR_TEXT: Record<string, string> = {
  abort_basis_unknown: 'Unknown abort basis',
  abort_exposure_unknown: 'The residual loss is unknown. Complete the abort terms first.',
  abort_type_not_in_schedule: 'The schedule has no tier for a termination settlement',
  activity_not_found: 'The schedule activity was not found in this project',
  amount_invalid: 'The amount is not a valid number',
  amount_not_positive: 'The amount must be greater than zero',
  assignee_not_project_member: 'The person is not a member of this project',
  assignment_expired: "The approver's assignment has expired; update the assignments",
  assignment_window_inverted: 'The assignment ends before it starts',
  cancellation_schedule_invalid: 'Each step needs a milestone, a date or progress, and exactly one charge',
  change_belongs_to_contract_item: 'A change and its contract are linked on the same item',
  commitment_not_in_matrix: 'This document is not in the commitment matrix',
  commitment_not_released: 'This commitment is not released for this amount',
  date_invalid: 'This is not a date',
  decision_invalid: 'Choose approve or reject',
  commitment_type_unknown: 'This commitment type is not in the authority schedule',
  contingency_insufficient: 'The contingency balance does not cover this drawdown',
  contingency_line_required: 'A contingency drawdown needs the budget line that holds the contingency',
  deferral_needs_reason: 'Write down why the item is deferred',
  document_linked_elsewhere: 'This document is already counted in another item',
  document_not_found: 'Document not found in this project',
  enforcement_invalid: 'Enforcement must be off, warn or block',
  external_approval_required: 'The amount is above every tier: attach the external approval reference',
  field_frozen: 'This field can no longer be changed for this item',
  field_required: 'This field cannot be empty',
  flag_unknown: 'This flag is not in the authority schedule',
  four_eyes_violation: 'Whoever requested, owns or confirmed for this item cannot decide it',
  four_eyes_requester_is_approver: 'Four-eyes: you cannot request a release you would approve yourself',
  fx_policy_invalid: 'Unknown exchange rate policy',
  fx_rate_missing: 'No exchange rate for this date: the release cannot be evaluated',
  gate_unknown: "This gate is not in the project's governance model",
  governance_area_required: 'An item tied to a gate needs a management area',
  governance_area_unknown: "This management area is not in the project's governance model",
  invalid_transition: 'This step is not possible in the current state',
  item_changed: 'The item changed in the meantime. Try again.',
  item_closed: 'The item is closed',
  item_code_taken: 'Another item already uses this code',
  item_not_found: 'Commitment item not found',
  link_kind_invalid: 'Unknown document kind',
  link_kind_not_supported: 'This document kind cannot be linked yet',
  link_not_found: 'Link not found',
  manage_required: 'Only someone who manages the matrix can do this',
  manual_amount_needs_currency: 'A manual estimate needs an amount and a currency',
  matrix_missing: 'This project has no commitment matrix yet',
  no_pending_release: 'There is no pending release request',
  no_route_for_tier: 'Nobody is assigned to the required tier yet',
  not_entitled_decider: 'You do not hold the tier this request is decided on',
  not_item_owner: 'Only the item owner or a manager can change this item',
  not_requester: 'Only the requester or a manager can withdraw this request',
  planned_source_invalid: 'Unknown source for the planned amount',
  planned_source_not_found: 'The budget line, cost line or position was not found in this project',
  precondition_is_computed: 'This precondition is read from its module and cannot be ticked',
  precondition_kind_invalid: 'Unknown precondition kind',
  precondition_needs_evidence: 'Attach the evidence reference',
  precondition_needs_ref: 'This precondition needs a reference',
  precondition_not_found: 'Precondition not found',
  preconditions_open: 'Open preconditions block this release',
  project_not_found: 'Project not found',
  rationale_required: 'Give a reason',
  release_decided: 'This release request is already decided',
  release_pending: 'A release request for this item is already running',
  requisition_not_found: 'The requisition was not found in this project',
  route_changed_since_accepted: 'The approval route of this tier was edited. A manager must pin it again.',
  route_must_belong_to_project: 'Only an approval route of this project can be pinned',
  route_not_found: 'Approval route not found',
  schedule_currency_mismatch: 'This schedule uses another currency than the releases already recorded',
  schedule_not_in_force: 'The pinned schedule is not in force today. Pin the version that is.',
  schedule_type_mismatch: 'This schedule does not know the commitment type of an existing item',
  tier_unknown: 'This tier is not in the authority schedule',
  transfer_links_stay_in_project:
    'Linked documents belong to this project. Unlink them before transferring to another project.',
  transfer_target_invalid: 'An item cannot be transferred to itself',
  transfer_target_not_open: 'The target item is closed or waiting for a decision',
  transferable_invalid: 'Unknown transfer option',
  type_fixed_after_release: 'The type cannot change once a release was requested',
  unknown_catalogue: 'Catalogue not found',
  catalogue_code_taken: 'Another catalogue already uses this code',
  catalogue_invalid: 'The catalogue is not valid',
  catalogue_retired: 'This catalogue is retired',
  commitment_guard_unavailable: 'The release check could not be made, so this was not allowed',
  decider_not_tier_holder: 'Approved by someone who does not hold the tier',
  four_eyes_no_approver: 'Nobody on this tier may decide this request under the four-eyes rule',
  edit_required: 'Your role cannot edit commitment items',
  abort_parameter_invalid: 'An abort parameter is a share between 0 and 1',
  abort_parameter_not_in_basis: 'The chosen abort basis does not have this parameter',
  assignment_needs_approver: 'Name the approver of this tier before a deputy or a validity period',
  external_approval_not_required:
    'This amount is decided by a tier of the schedule: remove the external approval reference',
  drawdown_released_by_commitment:
    'This drawdown is a released commitment item. Abort that item to take the money back.',
  release_expired:
    'The release of this item is past its validity date: request a renewed release before binding more',
  plant_item_not_found: 'The plant item was not found in this project',
  frame_document_not_found: 'The frame document was not found in this project',
  funding_application_not_found: 'The funding application was not found in this project',
  gates_not_in_use: 'This project does not use gates, so nothing can wait for one',
};

/** The sentence for a refusal code, translated when the locale has it. */
export function errorText(t: TFn, code: string, serverMessage?: string | null): string {
  const english = ERROR_TEXT[code] ?? serverMessage ?? humanizeCode(code);
  return t(['commitment', 'errors', code].join('.'), { defaultValue: english });
}
