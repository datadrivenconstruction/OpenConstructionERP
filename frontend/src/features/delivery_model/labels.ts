// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the delivery model screens show for a code: the closed
// vocabularies (statuses, kinds, bases, routes), the names of catalogue items
// (forms, parties, risk categories, criteria) and the sentences for findings
// and refusals. The vocabularies are written as key maps rather than built
// from the code at runtime, so the key test can enumerate them and a
// translator can find every key by grep.

import type {
  AllocationStatus,
  Basis,
  ContractingParty,
  DecisionStatus,
  DeliveryForm,
  Disposition,
  Finding,
  InstallBy,
  LocaleTexts,
  ModelStatus,
  ContractGroup,
  ContractItemStatus,
  OfiKind,
  OfiLinkKind,
  OfiRoute,
  OfiStatus,
  PackageEffectiveStatus,
  PackageKind,
  PackageLinkKind,
  PriceBasis,
} from './api';
import { ERROR_TEXT } from './errorText';

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];

export type TFn = (key: string, options?: Record<string, unknown>) => string;

export interface LabelContext {
  t: TFn;
  language: string;
  exists: (key: string) => boolean;
}

export const MODEL_STATUS: Record<ModelStatus, KeyText> = {
  draft: ['delivery_model.ui.model_status.draft', 'Draft'],
  under_evaluation: ['delivery_model.ui.model_status.under_evaluation', 'Comparing forms'],
  proposed: ['delivery_model.ui.model_status.proposed', 'In review'],
  approved: ['delivery_model.ui.model_status.approved', 'Approved'],
  binding: ['delivery_model.ui.model_status.binding', 'Binding'],
  reopened: ['delivery_model.ui.model_status.reopened', 'Reopened'],
};

export const DECISION_STATUS: Record<DecisionStatus, KeyText> = {
  proposed: ['delivery_model.decision_status.proposed', 'Proposed'],
  approved: ['delivery_model.decision_status.approved', 'Approved'],
  superseded: ['delivery_model.decision_status.superseded', 'Superseded'],
  withdrawn: ['delivery_model.decision_status.withdrawn', 'Withdrawn'],
  rejected: ['delivery_model.decision_status.rejected', 'Rejected'],
};

/** Why a binding frame document did not approve the decision it carries. */
export const APPROVAL_BLOCKED: Record<string, KeyText> = {
  approval_needs_change_request: [
    'delivery_model.blocked.approval_needs_change_request',
    'The frame document was already binding when this decision was proposed. Raise a change request on it; its approval approves the decision.',
  ],
  approval_not_ready: [
    'delivery_model.blocked.approval_not_ready',
    'The frame document is binding, but the delivery model has open errors. Fix them and the decision is approved.',
  ],
  four_eyes_proposer_is_approver: [
    'delivery_model.blocked.four_eyes_proposer_is_approver',
    'Four-eyes: the person who proposed the decision also approved the frame document. Someone else has to propose or approve.',
  ],
  approver_unknown: [
    'delivery_model.blocked.approver_unknown',
    'Four-eyes cannot be checked: the governance approval does not say who decided.',
  ],
};

export const ALLOCATION_STATUS: Record<AllocationStatus, KeyText> = {
  unconfirmed: ['delivery_model.allocation_status.unconfirmed', 'Unconfirmed'],
  confirmed: ['delivery_model.allocation_status.confirmed', 'Confirmed'],
  link_missing: ['delivery_model.allocation_status.link_missing', 'Risk link missing'],
};

export const BASIS: Record<Basis, KeyText> = {
  contract: ['delivery_model.ui.basis.contract', 'Contract'],
  insurance: ['delivery_model.ui.basis.insurance', 'Insurance'],
  shared_pain_gain: ['delivery_model.ui.basis.shared_pain_gain', 'Shared overrun and saving'],
  statute: ['delivery_model.ui.basis.statute', 'Law'],
  ground_baseline: ['delivery_model.ui.basis.ground_baseline', 'Ground baseline report'],
};

export const PACKAGE_KIND: Record<PackageKind, KeyText> = {
  design: ['delivery_model.package_kind.design', 'Design'],
  construction: ['delivery_model.package_kind.construction', 'Construction'],
  design_and_construction: ['delivery_model.package_kind.design_and_construction', 'Design and construction'],
  supply: ['delivery_model.package_kind.supply', 'Supply'],
  supply_and_install: ['delivery_model.package_kind.supply_and_install', 'Supply and install'],
  management_services: ['delivery_model.package_kind.management_services', 'Management services'],
  operation: ['delivery_model.package_kind.operation', 'Operation'],
  project_agreement: ['delivery_model.package_kind.project_agreement', 'Project agreement'],
};

export const PACKAGE_STATUS: Record<PackageEffectiveStatus, KeyText> = {
  planned: ['delivery_model.package_status.planned', 'Planned'],
  in_procurement: ['delivery_model.package_status.in_procurement', 'In procurement'],
  awarded: ['delivery_model.package_status.awarded', 'Awarded'],
  closed: ['delivery_model.package_status.closed', 'Closed'],
  cancelled: ['delivery_model.package_status.cancelled', 'Cancelled'],
};

export const PRICE_BASIS: Record<PriceBasis, KeyText> = {
  remeasure: ['delivery_model.ui.price_basis.remeasure', 'Measured quantities at unit rates'],
  lump_sum: ['delivery_model.ui.price_basis.lump_sum', 'Lump sum'],
  gmp: ['delivery_model.ui.price_basis.gmp', 'Guaranteed maximum price'],
  target_cost: ['delivery_model.ui.price_basis.target_cost', 'Target cost'],
  cost_reimbursable: ['delivery_model.ui.price_basis.cost_reimbursable', 'Cost plus fee'],
  availability_payment: ['delivery_model.ui.price_basis.availability_payment', 'Availability payment'],
};

export const CONTRACTING_PARTY: Record<ContractingParty, KeyText> = {
  owner: ['delivery_model.ui.contracting_party.owner', 'Owner'],
  manager: ['delivery_model.ui.contracting_party.manager', 'Construction manager'],
};

export const PACKAGE_LINK_KIND: Record<PackageLinkKind, KeyText> = {
  bid_package: ['delivery_model.ui.link_kind.bid_package', 'Bid package'],
  tender_package: ['delivery_model.ui.link_kind.tender_package', 'Tender package'],
  rfq: ['delivery_model.ui.link_kind.rfq', 'Request for quotation'],
  subcontract_agreement: ['delivery_model.ui.link_kind.subcontract_agreement', 'Subcontract agreement'],
  contract: ['delivery_model.ui.link_kind.contract', 'Contract'],
};

export const OFI_LINK_KIND: Record<OfiLinkKind, KeyText> = {
  rfq: ['delivery_model.ui.link_kind.rfq', 'Request for quotation'],
  purchase_order: ['delivery_model.ui.link_kind.purchase_order', 'Purchase order'],
  requisition: ['delivery_model.ui.link_kind.requisition', 'Requisition'],
};

export const OFI_KIND: Record<OfiKind, KeyText> = {
  equipment: ['delivery_model.ui.ofi_kind.equipment', 'Equipment'],
  material: ['delivery_model.ui.ofi_kind.material', 'Material'],
  design: ['delivery_model.ui.ofi_kind.design', 'Design'],
  service: ['delivery_model.ui.ofi_kind.service', 'Service'],
  utility: ['delivery_model.ui.ofi_kind.utility', 'Utility connection'],
};

export const CONTRACT_GROUP: Record<ContractGroup, KeyText> = {
  contract_form: ['delivery_model.ui.contract_group.contract_form', 'Contract form'],
  land_tenure: ['delivery_model.ui.contract_group.land_tenure', 'Land tenure'],
  utility_contract: ['delivery_model.ui.contract_group.utility_contract', 'Utility contract'],
  user_agreement: ['delivery_model.ui.contract_group.user_agreement', 'User agreement'],
  partner_structure: ['delivery_model.ui.contract_group.partner_structure', 'Partner structure'],
};

export const CONTRACT_STATUS: Record<ContractItemStatus, KeyText> = {
  draft: ['delivery_model.ui.contract_status.draft', 'Draft'],
  negotiating: ['delivery_model.ui.contract_status.negotiating', 'In negotiation'],
  agreed: ['delivery_model.ui.contract_status.agreed', 'Agreed'],
  signed: ['delivery_model.ui.contract_status.signed', 'Signed'],
  terminated: ['delivery_model.ui.contract_status.terminated', 'Terminated'],
};

export const OFI_ROUTE: Record<OfiRoute, KeyText> = {
  rfq: ['delivery_model.ui.ofi_route.rfq', 'Request for quotation'],
  purchase_order: ['delivery_model.ui.ofi_route.purchase_order', 'Purchase order'],
  requisition: ['delivery_model.ui.ofi_route.requisition', 'Requisition'],
  framework: ['delivery_model.ui.ofi_route.framework', 'Framework agreement'],
  existing_stock: ['delivery_model.ui.ofi_route.existing_stock', 'Already in stock'],
  none_yet: ['delivery_model.ui.ofi_route.none_yet', 'Not decided yet'],
};

export const OFI_STATUS: Record<OfiStatus, KeyText> = {
  identified: ['delivery_model.ui.ofi_status.identified', 'Identified'],
  route_set: ['delivery_model.ui.ofi_status.route_set', 'Route set'],
  ordered: ['delivery_model.ui.ofi_status.ordered', 'Ordered'],
  delivered: ['delivery_model.ui.ofi_status.delivered', 'Delivered'],
  handed_to_installer: ['delivery_model.ui.ofi_status.handed_to_installer', 'Handed to installer'],
};

export const INSTALL_BY: Record<InstallBy, KeyText> = {
  owner: ['delivery_model.ui.install_by.owner', 'The owner'],
  package: ['delivery_model.ui.install_by.package', 'A package of the plan'],
};

export const DISPOSITION: Record<Disposition, KeyText> = {
  keep: ['delivery_model.ui.disposition.keep', 'Keep as it is'],
  re_scope: ['delivery_model.ui.disposition.re_scope', 'Change its scope'],
  cancel: ['delivery_model.ui.disposition.cancel', 'Cancel it'],
};

export const DESIGN_RESPONSIBILITY: Record<DeliveryForm['design_responsibility'], KeyText> = {
  owner: ['delivery_model.ui.design_by.owner', 'The owner designs'],
  contractor: ['delivery_model.ui.design_by.contractor', 'The contractor designs'],
  split_at_stage: ['delivery_model.ui.design_by.split_at_stage', 'Owner starts the design, contractor finishes it'],
  shared: ['delivery_model.ui.design_by.shared', 'Designed together'],
};

export const CONTRACTS_HELD: Record<DeliveryForm['owner_construction_contracts'], KeyText> = {
  many: ['delivery_model.ui.contracts_held.many', 'The owner holds one contract per trade'],
  one: ['delivery_model.ui.contracts_held.one', 'The owner holds one construction contract'],
  one_per_package_managed: [
    'delivery_model.ui.contracts_held.one_per_package_managed',
    'One contract per package, run by a manager',
  ],
};

/** What a finding code says. Codes that are also refusal codes read from `delivery_model.errors.*` instead. */
export const FINDING: Record<string, KeyText> = {
  risk_unallocated: ['delivery_model.ui.finding.risk_unallocated', 'No party carries this risk yet.'],
  shared_needs_basis: ['delivery_model.ui.finding.shared_needs_basis', 'A shared risk needs a basis that says how it is shared.'],
  deviation_needs_rationale: [
    'delivery_model.ui.finding.deviation_needs_rationale',
    'This differs from the usual allocation. Write down why.',
  ],
  allocation_inconsistent_with_form: [
    'delivery_model.ui.finding.allocation_inconsistent_with_form',
    'This allocation does not fit the chosen form.',
  ],
  allocation_deviates_from_default: [
    'delivery_model.ui.finding.allocation_deviates_from_default',
    'Differs from the usual allocation for this form.',
  ],
  packages_inconsistent_with_form: [
    'delivery_model.ui.finding.packages_inconsistent_with_form',
    'The package plan does not fit the chosen form.',
  ],
  price_basis_inconsistent_with_form: [
    'delivery_model.ui.finding.price_basis_inconsistent_with_form',
    'The price basis is not one the chosen form allows.',
  ],
  contract_type_inconsistent_with_form: [
    'delivery_model.ui.finding.contract_type_inconsistent_with_form',
    'The linked contract has a type the chosen form does not use.',
  ],
  contract_item_kind_unknown: ['delivery_model.ui.finding.contract_item_kind_unknown', 'The kind is not in the pinned catalogue.'],
  contract_item_dates_invalid: ['delivery_model.ui.finding.contract_item_dates_invalid', 'The end date is before the start date.'],
  contract_item_without_counterparty: ['delivery_model.ui.finding.contract_item_without_counterparty', 'Name the counterparty once the item is agreed.'],
  contract_form_price_basis_inconsistent: ['delivery_model.ui.finding.contract_form_price_basis_inconsistent', 'The price basis is not one the chosen form allows.'],
  partner_shares_not_100: ['delivery_model.ui.finding.partner_shares_not_100', 'The partner shares do not add up to 100 percent.'],
  contract_group_missing: ['delivery_model.ui.finding.contract_group_missing', 'Nothing recorded for this part of the contract side.'],
  ofi_late_for_installer: ['delivery_model.ui.finding.ofi_late_for_installer', 'Arrives after the installer needs it.'],
  disposition_missing: ['delivery_model.ui.finding.disposition_missing', 'Say what happens to this package.'],
  form_mapping_unknown_target: [
    'delivery_model.ui.finding.form_mapping_unknown_target',
    'The new catalogue has no form with this code.',
  ],
  category_mapping_unknown_target: [
    'delivery_model.ui.finding.category_mapping_unknown_target',
    'The new catalogue has no risk category with this code.',
  ],
};

/** Why a form rule refused, as the finding's `params.reason`. */
export const FINDING_REASON: Record<string, KeyText> = {
  contractor_designs: ['delivery_model.ui.reason.contractor_designs', 'Under this form the contractor designs, so design risk sits with the contractor.'],
  owner_designs: ['delivery_model.ui.reason.owner_designs', 'Under this form the owner designs, so design risk sits with the owner.'],
  operator_carries_availability: [
    'delivery_model.ui.reason.operator_carries_availability',
    'Under this form the operator carries the availability of the asset.',
  ],
  owner_designs_no_design_and_build: [
    'delivery_model.ui.reason.owner_designs_no_design_and_build',
    'The owner designs under this form, so no package may both design and build.',
  ],
  one_design_and_construction_package: [
    'delivery_model.ui.reason.one_design_and_construction_package',
    'This form needs exactly one design and construction package.',
  ],
  gmp_package_missing: [
    'delivery_model.ui.reason.gmp_package_missing',
    'This form needs a management package with a guaranteed maximum price.',
  ],
  trade_package_under_gmp: [
    'delivery_model.ui.reason.trade_package_under_gmp',
    'Trade packages belong under the package with the guaranteed maximum price.',
  ],
  trade_contracts_held_by_owner: [
    'delivery_model.ui.reason.trade_contracts_held_by_owner',
    'Under this form the owner holds the trade contracts.',
  ],
  trade_contracts_held_by_manager: [
    'delivery_model.ui.reason.trade_contracts_held_by_manager',
    'Under this form the manager holds the trade contracts.',
  ],
  one_project_agreement: [
    'delivery_model.ui.reason.one_project_agreement',
    'This form needs exactly one project agreement.',
  ],
  parent_missing: ['delivery_model.ui.reason.parent_missing', 'The package it sits under no longer exists.'],
  parent_cycle: ['delivery_model.ui.reason.parent_cycle', 'Following the packages above it leads back to this package.'],
};

/** Every vocabulary map, for the test that proves each key resolves in en and de. */
export const ALL_KEY_MAPS: Record<string, Record<string, KeyText>> = {
  MODEL_STATUS,
  DECISION_STATUS,
  APPROVAL_BLOCKED,
  ALLOCATION_STATUS,
  BASIS,
  PACKAGE_KIND,
  PACKAGE_STATUS,
  PRICE_BASIS,
  CONTRACTING_PARTY,
  PACKAGE_LINK_KIND,
  OFI_LINK_KIND,
  OFI_KIND,
  OFI_ROUTE,
  OFI_STATUS,
  CONTRACT_GROUP,
  CONTRACT_STATUS,
  INSTALL_BY,
  DISPOSITION,
  DESIGN_RESPONSIBILITY,
  CONTRACTS_HELD,
  FINDING,
  FINDING_REASON,
};

/** Render a vocabulary entry. An unknown code shows humanised rather than as a raw key. */
export function vocab<T extends string>(t: TFn, map: Record<T, KeyText>, code: T | '' | null | undefined): string {
  if (!code) return '';
  const entry = map[code as T];
  if (!entry) return humanizeCode(code);
  return t(entry[0], { defaultValue: entry[1] });
}

/**
 * A catalogue code written for a reader: `design_build` becomes "Design build".
 *
 * The last resort when neither the API nor the locale names the item. It is
 * never a raw key, which is what a demo must not show.
 */
export function humanizeCode(code: string): string {
  const words = code.replace(/[_-]+/g, ' ').trim();
  if (!words) return '';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function fromTexts(texts: LocaleTexts | null | undefined, language: string): string {
  if (!texts) return '';
  const lang = language.split('-')[0] ?? 'en';
  return texts[language] ?? texts[lang] ?? texts.en ?? Object.values(texts)[0] ?? '';
}

/**
 * The name of a catalogue item: the message key when the locale has it (a
 * shipped catalogue), then the item's own texts (a tenant catalogue), then
 * the code written out.
 */
export function catalogueText(
  ctx: LabelContext,
  item: { key?: string | null; texts?: LocaleTexts | null; code: string },
): string {
  if (item.key && ctx.exists(item.key)) return ctx.t(item.key);
  return fromTexts(item.texts, ctx.language) || humanizeCode(item.code);
}

/** A catalogue sentence that may be missing: a description or a rationale. Empty when nothing names it. */
export function catalogueSentence(ctx: LabelContext, key: string | null | undefined): string {
  return key && ctx.exists(key) ? ctx.t(key) : '';
}

export function formName(ctx: LabelContext, form: DeliveryForm | null | undefined, code: string | null | undefined): string {
  if (!form) return code ? humanizeCode(code) : '';
  return catalogueText(ctx, { key: form.name_key, texts: form.labels, code: form.code });
}

/** A lookup from party code to its name, built from the parties a response carries. */
export function partyNamer(
  ctx: LabelContext,
  parties: ReadonlyArray<{ code: string; name_key?: string | null; labels?: LocaleTexts | null }>,
): (code: string | null | undefined) => string {
  const byCode = new Map(parties.map((p) => [p.code, p]));
  return (code) => {
    if (!code) return '';
    const party = byCode.get(code);
    return catalogueText(ctx, { key: party?.name_key, texts: party?.labels, code });
  };
}

/** The sentence for a refusal code, translated when the locale has it. */
export function errorText(t: TFn, code: string, serverMessage?: string | null): string {
  const english = ERROR_TEXT[code] ?? serverMessage ?? humanizeCode(code);
  return t(['delivery_model', 'errors', code].join('.'), { defaultValue: english });
}

/** What a finding says, and the form rule behind it when the finding names one. */
export function findingText(t: TFn, finding: Pick<Finding, 'code' | 'params'>): { text: string; reason: string } {
  const entry = FINDING[finding.code];
  const text = entry ? t(entry[0], { defaultValue: entry[1] }) : errorText(t, finding.code);
  const reasonCode = typeof finding.params?.reason === 'string' ? finding.params.reason : '';
  const reasonEntry = reasonCode ? FINDING_REASON[reasonCode] : undefined;
  return { text, reason: reasonEntry ? t(reasonEntry[0], { defaultValue: reasonEntry[1] }) : '' };
}
