// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the procurement screens show for a code: the closed vocabularies
// (concept and package state, threshold badge, lists, signals) and the names
// of catalogue items (procedures, criteria, jurisdictions). The vocabularies
// are written as key maps rather than built from the code at runtime, so the
// key test can enumerate them and a translator can find every key by grep.

import type {
  EvaluationMethod,
  GateOption,
  CallOffMode,
  CandidateList,
  CandidateSource,
  CapacitySignal,
  ConceptState,
  Finding,
  FrameworkState,
  Named,
  PackageKind,
  PackageState,
  PriceSignal,
  SoundingMethod,
  SplitBasis,
  TenderBasis,
  ThresholdStatus,
} from './api';

/** A message key and the English it stands for, handed to `t` as `defaultValue`. */
export type KeyText = readonly [key: string, english: string];

export type TFn = (key: string, options?: Record<string, unknown>) => string;

export interface LabelContext {
  t: TFn;
  language: string;
  exists: (key: string) => boolean;
}

export const CONCEPT_STATE: Record<ConceptState, KeyText> = {
  draft: ['procurement_concept.concept_state.draft', 'Draft'],
  in_review: ['procurement_concept.concept_state.in_review', 'In review'],
  approved: ['procurement_concept.concept_state.approved', 'Approved'],
  binding: ['procurement_concept.concept_state.binding', 'Binding'],
  reopened: ['procurement_concept.concept_state.reopened', 'Reopened'],
};

export const PACKAGE_STATE: Record<PackageState, KeyText> = {
  planned: ['procurement_concept.package_state.planned', 'Planned'],
  procedure_set: ['procurement_concept.package_state.procedure_set', 'Procedure set'],
  shortlisted: ['procurement_concept.package_state.shortlisted', 'Short-listed'],
  in_tender: ['procurement_concept.package_state.in_tender', 'In tender'],
  awarded: ['procurement_concept.package_state.awarded', 'Awarded'],
  cancelled: ['procurement_concept.package_state.cancelled', 'Cancelled'],
  on_hold: ['procurement_concept.package_state.on_hold', 'On hold'],
};

export const FRAMEWORK_STATE: Record<FrameworkState, KeyText> = {
  draft: ['procurement_concept.framework_state.draft', 'Draft'],
  active: ['procurement_concept.framework_state.active', 'Active'],
  expired: ['procurement_concept.framework_state.expired', 'Expired'],
  exhausted: ['procurement_concept.framework_state.exhausted', 'Exhausted'],
  terminated: ['procurement_concept.framework_state.terminated', 'Terminated'],
};

export const THRESHOLD_STATUS: Record<ThresholdStatus, KeyText> = {
  above: ['procurement_concept.threshold_status.above', 'Above threshold'],
  below: ['procurement_concept.threshold_status.below', 'Below threshold'],
  unconfirmed: ['procurement_concept.threshold_status.unconfirmed', 'Threshold unconfirmed'],
  unresolved: ['procurement_concept.threshold_status.unresolved', 'Currency unresolved'],
  unavailable: ['procurement_concept.threshold_status.unavailable', 'No threshold for this date'],
  not_applicable: ['procurement_concept.threshold_status.not_applicable', 'No threshold'],
};

/** Names of the codes the shipped catalogues use. A company catalogue may bring its own, with its own texts. */
export const JURISDICTION: Record<string, KeyText> = {
  eu: ['procurement_concept.jurisdiction.eu', 'European Union'],
  uk: ['procurement_concept.jurisdiction.uk', 'United Kingdom'],
  us_federal: ['procurement_concept.jurisdiction.us_federal', 'United States federal'],
  de_national: ['procurement_concept.jurisdiction.de_national', 'Germany, national'],
  none: ['procurement_concept.jurisdiction.none', 'No public procurement law'],
};

export const CLIENT_TYPE: Record<string, KeyText> = {
  central: ['procurement_concept.client_type.central', 'Central government'],
  sub_central: ['procurement_concept.client_type.sub_central', 'Sub-central authority'],
  utility: ['procurement_concept.client_type.utility', 'Utility'],
  private: ['procurement_concept.client_type.private', 'Private client'],
};

export const PACKAGE_KIND: Record<PackageKind, KeyText> = {
  design: ['procurement_concept.package_kind.design', 'Design'],
  works: ['procurement_concept.package_kind.works', 'Works'],
  supply: ['procurement_concept.package_kind.supply', 'Supply'],
  supply_and_install: ['procurement_concept.package_kind.supply_and_install', 'Supply and install'],
  services: ['procurement_concept.package_kind.services', 'Services'],
};

export const TENDER_BASIS: Record<TenderBasis, KeyText> = {
  detailed: ['procurement_concept.tender_basis.detailed', 'Detailed specification'],
  functional: ['procurement_concept.tender_basis.functional', 'Functional specification'],
  mixed: ['procurement_concept.tender_basis.mixed', 'Mixed'],
};

export const EVALUATION_METHOD: Record<EvaluationMethod, KeyText> = {
  lowest_price: ['procurement_concept.ui.evaluation.lowest_price', 'Lowest price'],
  best_value: ['procurement_concept.ui.evaluation.best_value', 'Best value: price and quality weighed'],
};

export const SPLIT_BASIS: Record<SplitBasis, KeyText> = {
  trade: ['procurement_concept.split_basis.trade', 'By trade'],
  section: ['procurement_concept.split_basis.section', 'By section'],
  system: ['procurement_concept.split_basis.system', 'By system'],
  whole: ['procurement_concept.split_basis.whole', 'Whole'],
};

export const CANDIDATE_LIST: Record<CandidateList, KeyText> = {
  long: ['procurement_concept.candidate_list.long', 'Long list'],
  short: ['procurement_concept.candidate_list.short', 'Short list'],
  excluded: ['procurement_concept.candidate_list.excluded', 'Excluded'],
};

export const CANDIDATE_SOURCE: Record<CandidateSource, KeyText> = {
  market_sounding: ['procurement_concept.candidate_source.market_sounding', 'Market sounding'],
  own_list: ['procurement_concept.candidate_source.own_list', 'Own list'],
  framework: ['procurement_concept.candidate_source.framework', 'Framework'],
  public_notice: ['procurement_concept.candidate_source.public_notice', 'Public notice'],
};

export const CAPACITY: Record<CapacitySignal, KeyText> = {
  ample: ['procurement_concept.capacity.ample', 'Ample'],
  adequate: ['procurement_concept.capacity.adequate', 'Adequate'],
  tight: ['procurement_concept.capacity.tight', 'Tight'],
  insufficient: ['procurement_concept.capacity.insufficient', 'Insufficient'],
};

export const PRICE: Record<PriceSignal, KeyText> = {
  below_estimate: ['procurement_concept.price.below_estimate', 'Below estimate'],
  in_line: ['procurement_concept.price.in_line', 'In line'],
  above_estimate: ['procurement_concept.price.above_estimate', 'Above estimate'],
  unknown: ['procurement_concept.price.unknown', 'Unknown'],
};

export const METHOD: Record<SoundingMethod, KeyText> = {
  meeting: ['procurement_concept.method.meeting', 'Meeting'],
  survey: ['procurement_concept.method.survey', 'Survey'],
  rfi: ['procurement_concept.method.rfi', 'Request for information'],
  notice: ['procurement_concept.method.notice', 'Prior notice'],
};

export const CALL_OFF_MODE: Record<CallOffMode, KeyText> = {
  direct: ['procurement_concept.ui.call_off_mode.direct', 'Direct call-off'],
  mini_competition: ['procurement_concept.ui.call_off_mode.mini_competition', 'Mini competition'],
};

export const PICKER_REASON: Record<string, KeyText> = {
  not_allowed_at_value: ['procurement_concept.picker.reason.not_allowed_at_value', 'Not allowed at this value'],
  private_procedure_for_public_client: [
    'procurement_concept.picker.reason.private_procedure_for_public_client',
    'Not for public clients above the threshold',
  ],
  public_procedure_for_private_client: [
    'procurement_concept.picker.reason.public_procedure_for_private_client',
    'Public clients only',
  ],
};

export const LEDGER_KIND: Record<string, KeyText> = {
  award_package: ['procurement_concept.ui.ledger.kind_award_package', 'Planned package'],
  purchase_order: ['procurement_concept.ui.ledger.kind_purchase_order', 'Purchase order'],
};

/** Every vocabulary map, for the test that proves each key resolves in en and de. */
export const ALL_KEY_MAPS: Record<string, Record<string, KeyText>> = {
  CONCEPT_STATE,
  PACKAGE_STATE,
  FRAMEWORK_STATE,
  THRESHOLD_STATUS,
  JURISDICTION,
  CLIENT_TYPE,
  PACKAGE_KIND,
  TENDER_BASIS,
  SPLIT_BASIS,
  CANDIDATE_LIST,
  CANDIDATE_SOURCE,
  CAPACITY,
  PRICE,
  METHOD,
  CALL_OFF_MODE,
  PICKER_REASON,
  LEDGER_KIND,
};

/**
 * A code written for a reader: `supply_and_install` becomes "Supply and install".
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

export type CatalogueItemKind = 'procedure' | 'criterion' | 'jurisdiction';

/**
 * The name of a catalogue item: the key the API sent, then the texts a company
 * catalogue carries, then the shipped key for the code, then the code itself.
 */
/** A gate as the reader knows it: its code, and the name the governance model gives it when it has one. */
export function gateName(ctx: LabelContext, gate: Pick<GateOption, 'code' | 'label'>): string {
  const label = gate.label;
  let name = '';
  if (label?.key && ctx.exists(label.key)) name = ctx.t(label.key);
  else if (label?.text) {
    const lang = ctx.language.split('-')[0] ?? 'en';
    name = label.text[ctx.language] ?? label.text[lang] ?? label.text.en ?? '';
  }
  return name && name !== gate.code ? `${gate.code} ${name}` : gate.code;
}

export function catalogueName(ctx: LabelContext, kind: CatalogueItemKind, item: Named | string | null | undefined): string {
  if (!item) return '';
  const named: Named = typeof item === 'string' ? { code: item } : item;
  if (named.name_key && ctx.exists(named.name_key)) return ctx.t(named.name_key);
  if (named.labels) {
    const lang = ctx.language.split('-')[0] ?? 'en';
    const text = named.labels[ctx.language] ?? named.labels[lang] ?? named.labels.en;
    if (text) return text;
  }
  const key = ['procurement_concept', 'catalogue', kind, named.code].join('.');
  if (ctx.exists(key)) return ctx.t(key);
  return humanizeCode(named.code);
}

/** The sentence for a refusal code, translated when the locale has it, else the server's own sentence. */
export function errorText(t: TFn, code: string, serverMessage?: string | null): string {
  return t(['procurement_concept', 'errors', code].join('.'), { defaultValue: serverMessage || humanizeCode(code) });
}

/** The sentence for a rule finding. */
export function findingText(t: TFn, finding: Pick<Finding, 'code'>): string {
  return t(['procurement_concept', 'findings', finding.code].join('.'), { defaultValue: humanizeCode(finding.code) });
}
