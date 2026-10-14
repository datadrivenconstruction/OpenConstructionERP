// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The plain logic behind the procurement screens: which button a state
// offers, why a button is off, what a form still misses, and how a form
// becomes a request body. No React here, so every rule is a unit test.
//
// Permissions are never worked out here. Whether the reader may act comes
// from the `can` flags the server sends with the concept; this file only
// turns a `false` into the sentence that explains it.

import type {
  EvaluationMethod,
  FrameworkLot,
  AdvanceReleaseKind,
  Capability,
  CandidateInput,
  CatalogueJurisdiction,
  ConceptInput,
  CandidateList,
  CandidateSource,
  Concept,
  ConceptAction,
  Finding,
  FrameworkInput,
  FrameworkLedger,
  FrameworkPatch,
  PackageInput,
  PackageKind,
  PackageView,
  ProfileCriterion,
  ProfileInput,
  ScheduleRow,
  ScoreInput,
  SoundingInput,
  SplitBasis,
  TenderBasis,
} from './api';
import type { KeyText } from './labels';

/** Null when the action is allowed, else the server error code whose sentence explains the refusal. */
export type Verdict = string | null;

/** A capability as a verdict: null when allowed, else the refusal code the server gave. */
export function capVerdict(cap: Capability | undefined, fallback: string): Verdict {
  if (!cap) return fallback;
  return cap.allowed ? null : (cap.reason ?? fallback);
}

/** Changing the plan (packages, concept settings): the server's `can.edit_plan`. */
export function editVerdict(concept: Concept): Verdict {
  return capVerdict(concept.can.edit_plan, 'concept_locked');
}

/** Naming the release gate by hand: the server's `can.set_gate_fields`. */
export function gateVerdict(concept: Concept): Verdict {
  return capVerdict(concept.can.set_gate_fields, 'manage_required');
}

/** Steering moves that stay open while the plan is locked (hold, short list, milestones): `can.steer`. */
export function steerVerdict(concept: Concept): Verdict {
  return capVerdict(concept.can.steer, 'not_procurement_owner');
}

export interface ConceptStep {
  action: ConceptAction;
  verdict: Verdict;
  primary: boolean;
}

/**
 * The hand moves the server says apply now. With gates there are two: submit
 * for the gate and return to draft; the governance gate approves. On a project
 * without gates the server also offers approval and reopening by hand.
 */
export function conceptSteps(concept: Concept): ConceptStep[] {
  const steps: ConceptStep[] = [];
  const submit = offer(concept.can.submit);
  const back = offer(concept.can.return);
  const approve = offer(concept.can.approve);
  const reopen = offer(concept.can.reopen);
  if (submit.show) steps.push({ action: 'submit', verdict: submit.verdict, primary: true });
  if (approve.show) steps.push({ action: 'approve', verdict: approve.verdict, primary: !submit.show });
  if (back.show) steps.push({ action: 'return', verdict: back.verdict, primary: false });
  if (reopen.show) steps.push({ action: 'reopen', verdict: reopen.verdict, primary: false });
  return steps;
}

/** The client types of a law that fall under its thresholds: all but the one it keeps for private clients. */
export function publicClientTypes(law: CatalogueJurisdiction | undefined): string[] {
  if (!law) return [];
  return law.client_types.filter((c) => c !== (law.private_client_type ?? 'private'));
}

export interface ConceptDraft {
  /** The catalogue as `source:id`. */
  catalogue: string;
  jurisdiction: string;
  public_client: boolean;
  client_type: string;
  vat_rate_pct: string;
  /** Null when the reader may not set the gate, so the field is never sent. */
  release_gate_code: string | null;
}

/**
 * The request body of the concept form. The catalogue is sent only when it is
 * new or changed, the gate only when the reader may set it and changed it. A
 * private client sends no client type: the server sets the law's own.
 */
export function conceptInput(concept: Concept | null, d: ConceptDraft): ConceptInput {
  const cut = d.catalogue.indexOf(':');
  const source = d.catalogue.slice(0, cut) === 'tenant' ? 'tenant' : 'shipped';
  const id = d.catalogue.slice(cut + 1);
  const body: ConceptInput = { jurisdiction: d.jurisdiction, public_client: d.public_client, vat_rate_pct: d.vat_rate_pct };
  if (!concept || concept.catalogue_source !== source || concept.catalogue_id !== id) {
    body.catalogue_source = source;
    body.catalogue_id = id;
  }
  if (d.public_client) body.client_type = d.client_type;
  if (d.release_gate_code !== null && d.release_gate_code !== (concept?.release_gate_code ?? '')) {
    body.release_gate_code = d.release_gate_code;
  }
  return body;
}

export function splitFindings(findings: Finding[]): { blocking: Finding[]; warnings: Finding[] } {
  return {
    blocking: findings.filter((f) => f.blocks_approval),
    warnings: findings.filter((f) => !f.blocks_approval),
  };
}

/* ── Amounts ──────────────────────────────────────────────────────────── */

/**
 * What a person typed as an amount, as the decimal string the API takes, or
 * null when it is not an amount. Accepts grouping by space or apostrophe and
 * either decimal separator ("1 250 000,50", "1,250,000.50"). Never goes
 * through a float, so no cent is lost on the way.
 */
export function parseAmount(input: string): string | null {
  let s = input.replace(/[\s\u00a0\u202f']/g, '');
  if (!s) return null;
  const comma = s.lastIndexOf(',');
  const dot = s.lastIndexOf('.');
  if (comma >= 0 && dot >= 0) {
    const decimal = comma > dot ? ',' : '.';
    const grouping = decimal === ',' ? '.' : ',';
    s = s.split(grouping).join('').replace(decimal, '.');
  } else if (comma >= 0) {
    s = /^\d{1,3}(,\d{3})+$/.test(s) ? s.split(',').join('') : s.replace(',', '.');
  } else if (/^\d{1,3}(\.\d{3}){2,}$/.test(s)) {
    s = s.split('.').join('');
  }
  return /^\d+(\.\d+)?$/.test(s) ? s : null;
}

function sameAmount(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return !a && !b;
  const norm = (v: string) => (v.includes('.') ? v.replace(/0+$/, '').replace(/\.$/, '') : v).replace(/^0+(?=\d)/, '');
  return norm(a) === norm(b);
}

/* ── Packages ─────────────────────────────────────────────────────────── */

export interface PackageDraft {
  estimated_value: string;
  currency: string;
  procedure_code: string;
  tender_basis: TenderBasis | '';
  split_basis: SplitBasis;
  lot_group: string;
  small_lot_exemption: boolean;
  is_advance: boolean;
  advance_reason: string;
  /** The act of the release gate that releases the advance package, as `kind:id`, or empty. */
  advance_release: string;
  need_date: string;
  /** The schedule milestone that drives the need date, or empty. */
  need_activity_id: string;
  lead_time_days: string;
  framework_agreement_id: string;
  prequal_profile_id: string;
  notes: string;
  evaluation_method: EvaluationMethod;
  /** The award criteria of a best value award, one row each. */
  weights: WeightRow[];
  /** The BOQ section the tender takes its scope lines from, by id, or empty. */
  cost_ref_id: string;
}

/** One award criterion as it is typed: a name and its share in percent. */
export interface WeightRow {
  name: string;
  weight: string;
}

export function packageDraft(view: PackageView): PackageDraft {
  const a = view.award;
  return {
    estimated_value: a?.estimated_value ?? '',
    currency: a?.currency ?? '',
    procedure_code: a?.procedure_code ?? '',
    tender_basis: a?.tender_basis ?? '',
    split_basis: a?.split_basis ?? 'whole',
    lot_group: a?.lot_group ?? '',
    small_lot_exemption: a?.small_lot_exemption ?? false,
    is_advance: a?.is_advance ?? false,
    advance_reason: a?.advance_reason ?? '',
    advance_release: a?.advance_release_kind && a.advance_release_id ? `${a.advance_release_kind}:${a.advance_release_id}` : '',
    need_date: a?.need_date ?? '',
    need_activity_id: a?.need_activity_id ?? '',
    lead_time_days: a?.lead_time_days == null ? '' : String(a.lead_time_days),
    framework_agreement_id: a?.framework_agreement_id ?? '',
    prequal_profile_id: a?.prequal_profile_id ?? '',
    notes: a?.notes ?? '',
    evaluation_method: a?.evaluation_method ?? 'lowest_price',
    weights: Object.entries(a?.evaluation_weights ?? {}).map(([name, weight]) => ({ name, weight: String(weight) })),
    cost_ref_id: a?.cost_ref_id ?? '',
  };
}

export type PackageProblem =
  | 'value_invalid'
  | 'currency_invalid'
  | 'advance_without_reason'
  | 'lead_time_invalid'
  | 'criterion_invalid'
  | 'criterion_twice'
  | 'weights_not_100';

export const PACKAGE_PROBLEM: Record<PackageProblem, KeyText> = {
  value_invalid: ['procurement_concept.ui.problem.value_invalid', 'The estimated value is not an amount.'],
  currency_invalid: [
    'procurement_concept.ui.problem.currency_invalid',
    'Give the currency as a three-letter code, for example EUR.',
  ],
  advance_without_reason: ['procurement_concept.errors.advance_without_reason', 'An advance package needs a reason.'],
  lead_time_invalid: [
    'procurement_concept.ui.problem.lead_time_invalid',
    'The lead time is a whole number of days between 0 and 1500.',
  ],
  criterion_invalid: [
    'procurement_concept.ui.problem.criterion_invalid',
    'Every award criterion needs a name and a weight between 0 and 100.',
  ],
  criterion_twice: ['procurement_concept.ui.problem.criterion_twice', 'An award criterion is named twice.'],
  weights_not_100: ['procurement_concept.ui.problem.award_weights_not_100', 'The weights of the award criteria must add up to 100.'],
};

/**
 * True when saving the draft removes award criteria the package holds: the
 * award goes by lowest price and criteria are stored. The form asks first.
 */
export function dropsCriteria(d: PackageDraft, original: PackageDraft): boolean {
  return d.evaluation_method === 'lowest_price' && Object.keys(toWeights(original.weights)).length > 0;
}

/** The most award criteria one package can carry. */
export const MAX_AWARD_CRITERIA = 20;

/** The rows the reader filled in: a row left wholly empty is not a criterion. */
function typedWeights(rows: WeightRow[]): WeightRow[] {
  return rows.filter((r) => r.name.trim() !== '' || r.weight.trim() !== '');
}

/** The sum of the typed weights, as a display string ("100", "87.5"). */
export function awardWeightsTotal(rows: WeightRow[]): string {
  return String(typedWeights(rows).reduce((acc, r) => acc + (hundredths(r.weight) || 0), 0) / 100);
}

/** The weights as the request carries them: `{criterion: percent}`, empty when there are none. */
export function toWeights(rows: WeightRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of typedWeights(rows)) out[r.name.trim()] = parseAmount(r.weight) ?? '0';
  return out;
}

function sameWeights(a: Record<string, string>, b: Record<string, string>): boolean {
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every((k) => k in b && sameAmount(a[k], b[k]));
}

export function packageProblems(d: PackageDraft): PackageProblem[] {
  const out: PackageProblem[] = [];
  const hasValue = d.estimated_value.trim() !== '';
  if (hasValue && parseAmount(d.estimated_value) === null) out.push('value_invalid');
  const cur = d.currency.trim();
  if ((cur && !/^[A-Za-z]{3}$/.test(cur)) || (hasValue && !cur)) out.push('currency_invalid');
  if (d.is_advance && !d.advance_reason.trim()) out.push('advance_without_reason');
  const lead = d.lead_time_days.trim();
  if (lead && (!/^\d+$/.test(lead) || Number(lead) > 1500)) out.push('lead_time_invalid');
  // Award criteria count for a best value award only; the rows of a lowest price award are left alone.
  const rows = d.evaluation_method === 'best_value' ? typedWeights(d.weights) : [];
  if (rows.length > 0) {
    const bad = rows.some((r) => {
      const w = hundredths(r.weight);
      return !r.name.trim() || r.name.trim().length > 64 || Number.isNaN(w) || w > 10000;
    });
    const names = rows.map((r) => r.name.trim());
    if (bad) out.push('criterion_invalid');
    if (new Set(names).size !== names.length) out.push('criterion_twice');
    if (!bad && rows.reduce((acc, r) => acc + hundredths(r.weight), 0) !== 10000) out.push('weights_not_100');
  }
  return out;
}

/**
 * The request body for a package: only what the reader changed. The server
 * keeps every field that is absent, so an untouched field is never sent back.
 */
export function toPackageInput(d: PackageDraft, original: PackageDraft): PackageInput {
  const out: PackageInput = {};
  if (!sameAmount(parseAmount(d.estimated_value), parseAmount(original.estimated_value))) {
    out.estimated_value = parseAmount(d.estimated_value);
  }
  const cur = d.currency.trim().toUpperCase();
  if (cur && cur !== original.currency.trim().toUpperCase()) out.currency = cur;
  if (d.procedure_code !== original.procedure_code) out.procedure_code = d.procedure_code || null;
  if (d.tender_basis !== original.tender_basis) out.tender_basis = d.tender_basis || null;
  if (d.split_basis !== original.split_basis) out.split_basis = d.split_basis;
  if (d.lot_group.trim() !== original.lot_group.trim()) out.lot_group = d.lot_group.trim();
  if (d.small_lot_exemption !== original.small_lot_exemption) out.small_lot_exemption = d.small_lot_exemption;
  if (d.is_advance !== original.is_advance) out.is_advance = d.is_advance;
  // The release act is one item of the picker: its kind and its id travel together, and clear together.
  const release = d.is_advance ? d.advance_release : '';
  if (release !== original.advance_release) {
    const cut = release.indexOf(':');
    out.advance_release_kind = release ? (release.slice(0, cut) as AdvanceReleaseKind) : null;
    out.advance_release_id = release ? release.slice(cut + 1) : null;
  }
  if (d.advance_reason.trim() !== original.advance_reason.trim()) out.advance_reason = d.advance_reason.trim();
  // A bound milestone owns the date, so the typed date is only sent while nothing is bound.
  if (d.need_activity_id !== original.need_activity_id) out.need_activity_id = d.need_activity_id || null;
  if (!d.need_activity_id && d.need_date !== original.need_date) out.need_date = d.need_date || null;
  if (d.lead_time_days.trim() !== original.lead_time_days.trim()) {
    out.lead_time_days = d.lead_time_days.trim() === '' ? null : Number(d.lead_time_days.trim());
  }
  if (d.framework_agreement_id !== original.framework_agreement_id) {
    out.framework_agreement_id = d.framework_agreement_id || null;
  }
  if (d.prequal_profile_id !== original.prequal_profile_id) out.prequal_profile_id = d.prequal_profile_id || null;
  if (d.notes.trim() !== original.notes.trim()) out.notes = d.notes.trim();
  if (d.evaluation_method !== original.evaluation_method) out.evaluation_method = d.evaluation_method;
  // Criteria belong to a best value award. Under lowest price the form hides them, so none may stay stored
  // behind it: they are cleared. The server refuses null here, an empty object is how they are cleared.
  const weights = d.evaluation_method === 'best_value' ? toWeights(d.weights) : {};
  if (!sameWeights(weights, toWeights(original.weights))) out.evaluation_weights = weights;
  // The kind and the id of the cost reference travel together, and clear together.
  if (d.cost_ref_id !== original.cost_ref_id) {
    out.cost_ref_kind = d.cost_ref_id ? 'boq_section' : null;
    out.cost_ref_id = d.cost_ref_id || null;
  }
  return out;
}

export type PackageMove = keyof PackageView['can'];

export interface MoveOffer {
  /** Whether the button belongs on the row at all. */
  show: boolean;
  verdict: Verdict;
}

/**
 * A capability as a button: left out when the server says the action does not
 * apply to the object as it is, visible and disabled with the reason when it
 * applies but is refused. A missing flag offers nothing.
 */
export function offer(cap: Capability | undefined): MoveOffer {
  if (!cap) return { show: false, verdict: 'permission_denied' };
  if (cap.allowed) return { show: true, verdict: null };
  return { show: cap.applies !== false, verdict: cap.reason ?? 'permission_denied' };
}

/**
 * True when the server says the action makes no sense for the object as it
 * is: the control is left out. A missing flag is not that; it is refused with
 * a reason, so the reader still sees the control.
 */
export function notApplicable(cap: Capability | undefined): boolean {
  return cap?.applies === false;
}

/** One move of a package, straight from the flag the server sent with the row. */
export function packageMove(view: PackageView, move: PackageMove): MoveOffer {
  return offer(view.can?.[move]);
}

const SUPPLY_KINDS: PackageKind[] = ['supply', 'supply_and_install'];

/** The name of the tender vehicle a package gets: a request for quotation for supply, a bid package otherwise. */
export function executionVehicle(view: PackageView): 'bid_package' | 'rfq' {
  return SUPPLY_KINDS.includes(view.package_kind as PackageKind) ? 'rfq' : 'bid_package';
}

/* ── Prequalification ─────────────────────────────────────────────────── */

/** Hundredths, so 33.33 + 33.33 + 33.34 adds up to exactly 100. */
function hundredths(value: string): number {
  const amount = parseAmount(value);
  return amount === null ? Number.NaN : Math.round(Number(amount) * 100);
}

/** The sum of the weights of the scored criteria, as a display string ("100", "87.5"). */
export function weightsTotal(criteria: Array<Pick<ProfileCriterion, 'kind' | 'weight'>>): string {
  const sum = criteria.filter((c) => c.kind === 'scored').reduce((acc, c) => acc + (hundredths(c.weight) || 0), 0);
  return String(sum / 100);
}

export interface ProfileDraft {
  name: string;
  pass_mark: string;
  validity_months: string;
  /** Selected criteria by code, with the weight typed for a scored one. */
  criteria: Array<{ code: string; kind: 'pass_fail' | 'scored'; weight: string }>;
}

export type ProfileProblem = 'name_required' | 'no_criteria' | 'weights_not_100' | 'pass_mark_invalid';

export const PROFILE_PROBLEM: Record<ProfileProblem, KeyText> = {
  name_required: ['procurement_concept.ui.problem.profile_name_required', 'Give the profile a name.'],
  no_criteria: ['procurement_concept.ui.problem.no_criteria', 'Choose at least one criterion.'],
  weights_not_100: [
    'procurement_concept.errors.prequal_weights_not_100',
    'The weights of the scored criteria must add up to 100.',
  ],
  pass_mark_invalid: ['procurement_concept.ui.problem.pass_mark_invalid', 'The pass mark is a number from 0 to 100.'],
};

export function profileProblems(d: ProfileDraft): ProfileProblem[] {
  const out: ProfileProblem[] = [];
  if (!d.name.trim()) out.push('name_required');
  if (d.criteria.length === 0) out.push('no_criteria');
  const scored = d.criteria.filter((c) => c.kind === 'scored');
  if (scored.length > 0) {
    const sum = scored.reduce((acc, c) => acc + hundredths(c.weight), 0);
    if (sum !== 10000) out.push('weights_not_100');
  }
  const mark = hundredths(d.pass_mark || '0');
  if (Number.isNaN(mark) || mark > 10000) out.push('pass_mark_invalid');
  return out;
}

export function toProfileInput(d: ProfileDraft, packageId: string | null): ProfileInput {
  return {
    package_id: packageId,
    name: d.name.trim(),
    criteria: d.criteria.map((c) => ({
      code: c.code,
      weight: c.kind === 'scored' ? (parseAmount(c.weight) ?? '0') : '0',
    })),
    pass_mark: parseAmount(d.pass_mark || '0') ?? '0',
    validity_months: Number(d.validity_months) || 12,
  };
}

export interface CandidateDraft {
  subcontractor_id: string;
  /** A vendor record instead of a subcontractor. Never both. */
  vendor_id?: string;
  free_name: string;
  source: CandidateSource;
  list: CandidateList;
  decision_rationale: string;
  conflict_of_interest_declared: boolean;
  conflict_note: string;
}

export type CandidateProblem = 'needs_company' | 'excluded_needs_rationale' | 'short_needs_registered';

export const CANDIDATE_PROBLEM: Record<CandidateProblem, KeyText> = {
  needs_company: [
    'procurement_concept.errors.candidate_needs_company',
    'Name the company or link a subcontractor or vendor.',
  ],
  excluded_needs_rationale: [
    'procurement_concept.errors.excluded_candidate_without_rationale',
    'Give a reason for excluding the candidate.',
  ],
  short_needs_registered: [
    'procurement_concept.errors.candidate_not_registered',
    'Register the company as subcontractor or vendor before short-listing it.',
  ],
};

/** The registered company of a draft as one picker value: `subcontractor:id`, `vendor:id` or empty. */
export function companyValue(d: Pick<CandidateDraft, 'subcontractor_id' | 'vendor_id'>): string {
  if (d.subcontractor_id) return `subcontractor:${d.subcontractor_id}`;
  return d.vendor_id ? `vendor:${d.vendor_id}` : '';
}

/** The two links a picker value stands for. Choosing one always clears the other. */
export function companyLinks(value: string): { subcontractor_id: string; vendor_id: string } {
  const cut = value.indexOf(':');
  const kind = cut < 0 ? '' : value.slice(0, cut);
  const id = cut < 0 ? '' : value.slice(cut + 1);
  return { subcontractor_id: kind === 'subcontractor' ? id : '', vendor_id: kind === 'vendor' ? id : '' };
}

/** `registered` stands for a link the draft does not carry. */
export function candidateProblems(d: CandidateDraft, registered = false): CandidateProblem[] {
  const out: CandidateProblem[] = [];
  const linked = registered || !!d.subcontractor_id || !!d.vendor_id;
  if (!linked && !d.free_name.trim()) out.push('needs_company');
  if (d.list === 'excluded' && !d.decision_rationale.trim()) out.push('excluded_needs_rationale');
  if (d.list === 'short' && !linked) out.push('short_needs_registered');
  return out;
}

export function toCandidateInput(d: CandidateDraft): CandidateInput {
  const linked = !!d.subcontractor_id || !!d.vendor_id;
  return {
    subcontractor_id: d.subcontractor_id || null,
    vendor_id: d.subcontractor_id ? null : d.vendor_id || null,
    // A registered company carries its own name.
    free_name: linked ? '' : d.free_name.trim(),
    source: d.source,
    list: d.list,
    decision_rationale: d.decision_rationale.trim(),
    conflict_of_interest_declared: d.conflict_of_interest_declared,
    conflict_note: d.conflict_note.trim(),
  };
}

/** One row of the scoring form: a verdict for pass or fail, points for a scored criterion. */
export interface ScoreDraft {
  criterion_code: string;
  kind: 'pass_fail' | 'scored';
  passed: '' | 'yes' | 'no';
  score: string;
}

/** True when every typed score is a number from 0 to 100. */
export function scoresValid(rows: ScoreDraft[]): boolean {
  return rows.every((r) => {
    if (r.kind !== 'scored' || !r.score.trim()) return true;
    const v = hundredths(r.score);
    return !Number.isNaN(v) && v <= 10000;
  });
}

/** Only the rows the reader assessed. A pass or fail criterion never carries points. */
export function toScoreInputs(rows: ScoreDraft[]): ScoreInput[] {
  const out: ScoreInput[] = [];
  for (const r of rows) {
    if (r.kind === 'pass_fail') {
      if (r.passed) out.push({ criterion_code: r.criterion_code, passed: r.passed === 'yes' });
    } else if (r.score.trim()) {
      out.push({ criterion_code: r.criterion_code, score: parseAmount(r.score) });
    }
  }
  return out;
}

/* ── Market sounding ──────────────────────────────────────────────────── */

export type SoundingDraft = Omit<SoundingInput, 'lead_time_signal_days'> & { lead_time_signal_days: string };

/** Tight or insufficient capacity that names neither a mitigation nor a new split: the rule the server warns on. */
export function soundingUnmitigated(d: Pick<SoundingDraft, 'capacity_signal' | 'mitigation' | 'resplit'>): boolean {
  return (d.capacity_signal === 'tight' || d.capacity_signal === 'insufficient') && !d.mitigation.trim() && !d.resplit;
}

export function soundingReady(d: SoundingDraft): boolean {
  const days = d.lead_time_signal_days.trim();
  return !!d.held_on && (!days || (/^\d+$/.test(days) && Number(days) <= 1500));
}

/**
 * The request body of a sounding. The participants travel only when the
 * reader changed them (`stored` is the list the record holds): the server
 * looks up every id it is sent, so an untouched list is never sent back.
 */
export function toSoundingInput(d: SoundingDraft, stored: string[] = []): SoundingInput {
  const { participant_candidate_ids: picked = [], ...rest } = d;
  const out: SoundingInput = {
    ...rest,
    trade: d.trade.trim(),
    findings: d.findings.trim(),
    mitigation: d.mitigation.trim(),
    lead_time_signal_days: d.lead_time_signal_days.trim() === '' ? null : Number(d.lead_time_signal_days.trim()),
  };
  const same = picked.length === stored.length && picked.every((id) => stored.includes(id));
  if (!same) out.participant_candidate_ids = picked;
  return out;
}

/* ── Award schedule ───────────────────────────────────────────────────── */

/** A proposal exists only once the package has a need date and a procedure. */
export function hasProposal(row: ScheduleRow): boolean {
  return !!row.proposed_award_date && !!row.proposed_start_date;
}

/** Both milestones are already in the project schedule. Confirming again moves their dates. */
export function isConfirmed(row: ScheduleRow): boolean {
  return !!row.start_activity_id && !!row.award_activity_id;
}

/* ── Framework agreements ─────────────────────────────────────────────── */

export type FrameworkDraft = FrameworkInput;

export type FrameworkProblem =
  | 'code_required'
  | 'value_invalid'
  | 'currency_invalid'
  | 'dates_required'
  | 'dates_inverted'
  | 'lot_code_required';

export const FRAMEWORK_PROBLEM: Record<FrameworkProblem, KeyText> = {
  code_required: ['procurement_concept.ui.problem.framework_code_required', 'Give the agreement a code.'],
  value_invalid: ['procurement_concept.ui.problem.framework_value_invalid', 'The maximum value is not an amount.'],
  currency_invalid: [
    'procurement_concept.ui.problem.currency_invalid',
    'Give the currency as a three-letter code, for example EUR.',
  ],
  dates_required: ['procurement_concept.ui.problem.framework_dates_required', 'Give the start and the end date.'],
  dates_inverted: ['procurement_concept.errors.framework_dates_inverted', 'The end date is before the start date.'],
  lot_code_required: ['procurement_concept.ui.problem.lot_code_required', 'Give every lot a code.'],
};

export function frameworkProblems(d: FrameworkDraft): FrameworkProblem[] {
  const out: FrameworkProblem[] = [];
  if (!d.code.trim()) out.push('code_required');
  if (parseAmount(d.max_value) === null) out.push('value_invalid');
  if (!/^[A-Za-z]{3}$/.test(d.currency.trim())) out.push('currency_invalid');
  if (!d.start_date || !d.end_date) out.push('dates_required');
  else if (d.end_date < d.start_date) out.push('dates_inverted');
  if (typedLots(d.lots).some((l) => !l.code)) out.push('lot_code_required');
  return out;
}

/** The lots the reader filled in, trimmed. A row left wholly empty is not a lot. */
export function typedLots(lots: FrameworkLot[] | undefined): FrameworkLot[] {
  return (lots ?? [])
    .map((l) => ({ code: (l.code ?? '').trim(), title: (l.title ?? '').trim() }))
    .filter((l) => l.code !== '' || l.title !== '');
}

function sameLots(a: FrameworkLot[], b: FrameworkLot[]): boolean {
  return a.length === b.length && a.every((l, i) => l.code === b[i]?.code && l.title === b[i]?.title);
}

export function toFrameworkInput(d: FrameworkDraft): FrameworkInput {
  return {
    ...d,
    lots: typedLots(d.lots),
    subcontractor_id: d.subcontractor_id || null,
    vendor_id: d.subcontractor_id ? null : d.vendor_id || null,
    code: d.code.trim(),
    title: d.title.trim(),
    supplier_name: d.supplier_name.trim(),
    scope: d.scope.trim(),
    max_value: parseAmount(d.max_value) ?? '0',
    currency: d.currency.trim().toUpperCase(),
    source_procedure_ref: d.source_procedure_ref.trim(),
  };
}

/**
 * An existing agreement keeps its code, currency and start date; the rest can
 * change. The lots travel only when they differ from the `stored` ones, and
 * the supplier link only when it differs from the one the agreement `holds`.
 */
export function toFrameworkPatch(
  d: FrameworkDraft,
  stored?: FrameworkLot[],
  holds?: { subcontractor_id: string | null; vendor_id: string | null },
): FrameworkPatch {
  const full = toFrameworkInput(d);
  const lots = full.lots ?? [];
  const relinked =
    holds !== undefined &&
    ((full.subcontractor_id ?? null) !== (holds.subcontractor_id ?? null) || (full.vendor_id ?? null) !== (holds.vendor_id ?? null));
  return {
    ...(relinked ? { subcontractor_id: full.subcontractor_id, vendor_id: full.vendor_id } : {}),
    ...(stored !== undefined && !sameLots(lots, typedLots(stored)) ? { lots } : {}),
    title: full.title,
    supplier_name: full.supplier_name,
    scope: full.scope,
    package_kinds: full.package_kinds,
    max_value: full.max_value,
    end_date: full.end_date,
    call_off_mode: full.call_off_mode,
    source_procedure_ref: full.source_procedure_ref,
  };
}

/** How much of the agreement is called off, from 0 to 1, for the bar. Display only, never for a decision. */
export function calledOffShare(ledger: Pick<FrameworkLedger, 'max_value' | 'call_off_value'>): number {
  const max = Number(ledger.max_value);
  const used = Number(ledger.call_off_value);
  if (!Number.isFinite(max) || !Number.isFinite(used) || max <= 0) return 0;
  return Math.min(1, Math.max(0, used / max));
}
