// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The arithmetic and the draft checks of the delivery model screens, kept
// free of React so each one is a plain unit test.
//
// Nothing here decides anything: the server repeats every check and owns the
// weighted totals. These functions only tell the reader what is still missing
// before a request is worth sending, and they add decimal strings without
// going through floats so "33.3 + 33.3 + 33.4" reads as 100.

import type {
  AllocationInput,
  AllocationItem,
  Basis,
  Comparison,
  DeliveryOption,
  DeliveryPackage,
  ModelStatus,
  OfiInput,
  OfiStatus,
  PackageInput,
  PackageStatus,
} from './api';
import type { KeyText } from './labels';

/** A decimal string as whole hundredths, or null when it is not a plain non-negative decimal. */
export function toHundredths(value: string | null | undefined): number | null {
  const text = (value ?? '').trim();
  const match = /^(\d+)(?:\.(\d{1,2})0*)?$/.exec(text);
  if (!match) return null;
  const whole = Number(match[1]);
  const fraction = Number((match[2] ?? '').padEnd(2, '0'));
  return whole * 100 + fraction;
}

/** Hundredths written back as a decimal string without trailing zeros: 10000 is "100", 3350 is "33.5". */
export function fromHundredths(value: number): string {
  const whole = Math.trunc(value / 100);
  const fraction = Math.abs(value % 100);
  if (fraction === 0) return String(whole);
  return `${whole}.${String(fraction).padStart(2, '0').replace(/0$/, '')}`;
}

/** The sum of decimal strings in hundredths, or null when any of them is not a number. */
export function sumHundredths(values: ReadonlyArray<string>): number | null {
  let total = 0;
  for (const v of values) {
    const h = toHundredths(v);
    if (h === null) return null;
    total += h;
  }
  return total;
}

export type WeightsProblem = 'weight_invalid' | 'weights_not_100' | null;

/** Weights must each be a number from 0 to 100 and add up to exactly 100. */
export function weightsProblem(weights: Record<string, string>): WeightsProblem {
  const values = Object.values(weights);
  const invalid = values.some((v) => {
    const h = toHundredths(v);
    return h === null || h > 10000;
  });
  if (invalid) return 'weight_invalid';
  return sumHundredths(values) === 10000 ? null : 'weights_not_100';
}

const cellKey = (optionId: string, criterionCode: string) => `${optionId}|${criterionCode}`;

/** Scores by option and criterion, for the comparison grid. */
export function scoreMap(comparison: Pick<Comparison, 'scores'>): Map<string, number> {
  const map = new Map<string, number>();
  for (const s of comparison.scores) if (s.criterion_code) map.set(cellKey(s.option_id, s.criterion_code), s.score);
  return map;
}

export function scoreOf(map: Map<string, number>, optionId: string, criterionCode: string): number | null {
  return map.get(cellKey(optionId, criterionCode)) ?? null;
}

/** How many cells of the grid still have no score. */
export function missingScores(comparison: Comparison): number {
  const map = scoreMap(comparison);
  let missing = 0;
  for (const o of comparison.options) for (const c of comparison.criteria) if (!map.has(cellKey(o.id, c.code))) missing += 1;
  return missing;
}

/**
 * The option with the highest weighted total, as the server computed it.
 * Null while no option is fully scored. A tie goes to the option listed first,
 * which is a display rule only: the reader still chooses which form to propose.
 */
export function leadingOptionId(options: ReadonlyArray<Pick<DeliveryOption, 'id' | 'weighted_total'>>): string | null {
  let best: { id: string; total: number } | null = null;
  for (const o of options) {
    // Ranking only, never arithmetic: the total has more decimals than a weight.
    const total = o.weighted_total === null || o.weighted_total === '' ? NaN : Number(o.weighted_total);
    if (!Number.isFinite(total)) continue;
    if (!best || total > best.total) best = { id: o.id, total };
  }
  return best?.id ?? null;
}

/** Problems a screen names itself; every other code reads from `delivery_model.errors.*`. */
export const PROBLEM: Record<string, KeyText> = {
  party_required: ['delivery_model.ui.problem.party_required', 'Choose who carries the risk, or mark it not applicable.'],
  code_required: ['delivery_model.ui.problem.code_required', 'Give it a short code, for example P-01.'],
  code_invalid: [
    'delivery_model.ui.problem.code_invalid',
    'A code starts with a letter or digit and uses only letters, digits, dot, dash and underscore.',
  ],
  title_required: ['delivery_model.ui.problem.title_required', 'Give the package a title.'],
  description_required: ['delivery_model.ui.problem.description_required', 'Describe the item.'],
  installer_required: ['delivery_model.ui.problem.installer_required', 'Choose the package that installs it.'],
  option_required: ['delivery_model.ui.problem.option_required', 'Choose the form to propose.'],
  record_required: ['delivery_model.ui.problem.record_required', 'Choose the record to link.'],
  // the server reports this one as a finding, so the sentence is the finding's own
  shared_needs_basis: ['delivery_model.ui.finding.shared_needs_basis', 'A shared risk needs a basis that says how it is shared.'],
};

/**
 * What still stops a proposal, in the order the reader fixes it. The codes are
 * the server's own refusal codes, so the sentence is the same before and after
 * the request.
 */
export function proposeProblems(
  comparison: Comparison,
  draft: { optionId: string | null; rationale: string },
): string[] {
  const problems: string[] = [];
  if (comparison.options.length < 2) problems.push('single_option_decision');
  if (toHundredths(comparison.weights_total) !== 10000) problems.push('weights_not_100');
  if (missingScores(comparison) > 0) problems.push('scores_incomplete');
  if (!draft.optionId) problems.push('option_required');
  else if (!comparison.options.some((o) => o.id === draft.optionId)) problems.push('chosen_option_unknown');
  if (!draft.rationale.trim()) problems.push('rationale_missing');
  return problems;
}

export const SHARED_PARTY = 'shared';

/** A shared risk is shared through one of these mechanisms, never simply "by contract". */
export const SHARED_BASES: ReadonlyArray<Basis> = ['shared_pain_gain', 'ground_baseline'];

export type CellState = 'empty' | 'default' | 'unconfirmed' | 'confirmed' | 'link_missing' | 'not_applicable';

/**
 * How a matrix row reads: nothing at all, the catalogue default nobody has
 * confirmed, an edited but unconfirmed allocation, a confirmed one, or a
 * confirmed one whose risk register entry was deleted.
 */
export function cellState(item: Pick<AllocationItem, 'allocation' | 'default'>): CellState {
  const a = item.allocation;
  if (!a) return item.default ? 'default' : 'empty';
  if (a.not_applicable) return 'not_applicable';
  return a.status;
}

/** What the row shows: the project's own allocation, else the catalogue default. */
export function shownAllocation(
  item: Pick<AllocationItem, 'allocation' | 'default'>,
): { party: string | null; basis: Basis; shares: Record<string, string> } | null {
  if (item.allocation) {
    return { party: item.allocation.party, basis: item.allocation.basis, shares: item.allocation.shares ?? {} };
  }
  if (item.default) return { party: item.default.party, basis: item.default.basis, shares: item.default.shares ?? {} };
  return null;
}

export interface MatrixSummary {
  total: number;
  confirmed: number;
  toConfirm: number;
  errors: number;
  warnings: number;
  /** Confirmed allocations with no risk register entry yet. */
  seedable: number;
}

export function matrixSummary(items: ReadonlyArray<AllocationItem>): MatrixSummary {
  const out: MatrixSummary = { total: items.length, confirmed: 0, toConfirm: 0, errors: 0, warnings: 0, seedable: 0 };
  for (const item of items) {
    const state = cellState(item);
    const settled = state === 'confirmed' || state === 'link_missing' || (state === 'not_applicable' && item.allocation?.status === 'confirmed');
    if (settled) out.confirmed += 1;
    else out.toConfirm += 1;
    for (const f of item.findings) {
      if (f.severity === 'error') out.errors += 1;
      else if (f.severity === 'warning') out.warnings += 1;
    }
    const a = item.allocation;
    if (a && a.status === 'confirmed' && !a.not_applicable && a.risk_item_ids.length === 0) out.seedable += 1;
  }
  return out;
}

/** What is wrong with an allocation draft, as refusal codes. Empty means it is worth sending. */
export function allocationProblems(draft: AllocationInput): string[] {
  const problems: string[] = [];
  if (draft.not_applicable) {
    if (!draft.rationale.trim()) problems.push('not_applicable_needs_rationale');
    return problems;
  }
  if (!draft.party) problems.push('party_required');
  if (draft.party === SHARED_PARTY) {
    const entries = Object.entries(draft.shares).filter(([, v]) => v.trim() !== '');
    const values = entries.map(([, v]) => toHundredths(v));
    if (values.some((v) => v === null || v <= 0)) problems.push('share_invalid');
    else if (entries.length < 2) problems.push('shared_needs_two_parties');
    else if (values.reduce<number>((sum, v) => sum + (v ?? 0), 0) !== 10000) problems.push('shared_risk_not_100');
    if (!SHARED_BASES.includes(draft.basis)) problems.push('shared_needs_basis');
  }
  return problems;
}

/** The body to send: shares only travel with a shared risk, and empty share fields are dropped. */
export function toAllocationInput(draft: AllocationInput): AllocationInput {
  if (draft.not_applicable) return { ...draft, party: null, shares: {}, rationale: draft.rationale.trim() };
  const shares: Record<string, string> = {};
  if (draft.party === SHARED_PARTY) {
    for (const [party, value] of Object.entries(draft.shares)) if (value.trim() !== '') shares[party] = value.trim();
  }
  return { ...draft, shares, rationale: draft.rationale.trim() };
}

const CODE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

function codeProblem(code: string): string | null {
  if (!code.trim()) return 'code_required';
  return CODE_PATTERN.test(code.trim()) ? null : 'code_invalid';
}

export function packageProblems(draft: Pick<PackageInput, 'code' | 'title'>, isNew: boolean): string[] {
  const problems: string[] = [];
  const code = isNew ? codeProblem(draft.code) : null;
  if (code) problems.push(code);
  if (!draft.title.trim()) problems.push('title_required');
  return problems;
}

export function ofiProblems(
  draft: Pick<OfiInput, 'code' | 'description' | 'install_by' | 'package_id'>,
  isNew: boolean,
): string[] {
  const problems: string[] = [];
  const code = isNew ? codeProblem(draft.code) : null;
  if (code) problems.push(code);
  if (!draft.description.trim()) problems.push('description_required');
  if (draft.install_by === 'package' && !draft.package_id) problems.push('installer_required');
  return problems;
}

export interface PackageRow {
  pkg: DeliveryPackage;
  depth: number;
}

/**
 * Packages in plan order with each one's children right under it. A package
 * whose parent is not in the list is shown at the top level instead of being
 * dropped, so a broken parent link never hides a row.
 */
export function packageTree(packages: ReadonlyArray<DeliveryPackage>): PackageRow[] {
  const ids = new Set(packages.map((p) => p.id));
  const children = new Map<string, DeliveryPackage[]>();
  const roots: DeliveryPackage[] = [];
  for (const p of packages) {
    if (p.parent_id && ids.has(p.parent_id) && p.parent_id !== p.id) {
      const list = children.get(p.parent_id) ?? [];
      list.push(p);
      children.set(p.parent_id, list);
    } else roots.push(p);
  }
  const out: PackageRow[] = [];
  const seen = new Set<string>();
  const walk = (p: DeliveryPackage, depth: number) => {
    if (seen.has(p.id)) return;
    seen.add(p.id);
    out.push({ pkg: p, depth });
    for (const child of children.get(p.id) ?? []) walk(child, depth + 1);
  };
  for (const root of roots) walk(root, 0);
  // A cycle of parents has no root; show its members flat rather than lose them.
  for (const p of packages) if (!seen.has(p.id)) walk(p, 0);
  return out;
}

export type ResponsibilityFilter = 'all' | 'designs' | 'builds' | 'supplies';

/** "Who designs, builds or supplies": the plan without cancelled packages, narrowed to one duty. */
export function filterPackages(packages: ReadonlyArray<DeliveryPackage>, filter: ResponsibilityFilter): DeliveryPackage[] {
  if (filter === 'all') return [...packages];
  return packages.filter((p) => p.effective_status !== 'cancelled' && p[filter]);
}

/** The stored states a package may move to. A linked package reads its progress from the linked record. */
export function nextPackageStatuses(status: PackageStatus): PackageStatus[] {
  return status === 'planned' ? ['closed', 'cancelled'] : ['planned'];
}

const OFI_ORDER: OfiStatus[] = ['identified', 'route_set', 'ordered', 'delivered', 'handed_to_installer'];

/** The next step of an owner-furnished item, or null at the end. Setting the route is its own action. */
export function nextOfiStatus(status: OfiStatus): OfiStatus | null {
  if (status === 'identified') return null;
  return OFI_ORDER[OFI_ORDER.indexOf(status) + 1] ?? null;
}

/**
 * The fields of `after` that differ from `before`. A PATCH carries only these:
 * the server reads an explicit null as "clear this field" and refuses a null
 * on a field that cannot be empty, so an untouched field must not travel.
 */
export function changedFields<T extends object>(before: T, after: T): Partial<T> {
  const out: Partial<T> = {};
  for (const key of Object.keys(after) as Array<keyof T>) {
    if (JSON.stringify(after[key] ?? null) !== JSON.stringify(before[key] ?? null)) out[key] = after[key];
  }
  return out;
}

/** Comparison, weights, scores and owner situation can change in these states only. */
export function comparisonEditable(status: ModelStatus): boolean {
  return status === 'draft' || status === 'under_evaluation' || status === 'reopened';
}

/** Allocations stay editable while a decision is proposed and freeze once it is approved. */
export function allocationsFrozen(status: ModelStatus): boolean {
  return status === 'approved' || status === 'binding';
}
