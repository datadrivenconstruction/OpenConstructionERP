// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Design Options module.
 *
 * A design option set holds two or more competing design options for the same
 * project (for example a concrete frame versus a steel frame). An option is a
 * whole alternative, not a model: it can carry its own BIM/CAD model, which is
 * converted and priced into its own bill of quantities, and it can just as well
 * point at an estimate, a programme and a carbon inventory the project already
 * holds. That is what lets the options be compared like for like on what they
 * cost, when they finish and what they emit.
 *
 * Everything an option references is PICKED, never re-uploaded. The model comes
 * from the federated project-files dialog and the rest from the project's own
 * registers, because asking for a second copy of a file the platform already
 * stores is how a project ends up with two of everything.
 *
 * Backed by /api/v1/design-options/ - see backend/app/modules/design_options.
 *
 * Money, quantity, rate and ratio values ride as Decimal-as-string in JSON so
 * large totals round-trip without binary-float drift and stay locale-neutral.
 * Every such field below is typed `string`; parse to a number only for display
 * formatting, never for storage or arithmetic that feeds a bill of quantities.
 */

import {
  apiGet,
  apiPost,
  apiDelete,
  getAuthToken,
  extractErrorMessageFromBody,
  triggerDownload,
  API_BASE,
  type Page,
} from '@/shared/lib/api';

const BASE = '/v1/design-options';

/* ── Domain types ──────────────────────────────────────────────────────── */

/** Lifecycle of a single design option. */
export type DesignOptionStatus =
  | 'draft'
  | 'model_attached'
  | 'converting'
  | 'boq_generating'
  | 'priced'
  | 'failed';

/** Lifecycle of an option set. */
export type DesignOptionSetStatus = 'draft' | 'active' | 'decided' | 'archived';

/**
 * Where an option's bill of quantities came from. A `linked` bill is shared
 * with whatever else in the project uses it, so it is not this module's to
 * overwrite; a `generated` one was written here from the matched model.
 */
export type DesignOptionBoqSource = '' | 'generated' | 'linked';

/** Traffic-light validation state carried per option / per comparison column. */
export type OptionValidationStatus = 'pending' | 'passed' | 'warnings' | 'errors';

/** One elemental line of an option's cost breakdown (stable `key` for i18n). */
export interface DesignOptionBreakdownRow {
  key: string;
  label: string;
  /** Share of the option total, as a percentage string. */
  cost_share_pct: string;
  /** Element total money, Decimal-as-string. */
  amount: string;
}

/** A single design option persisted under a set. */
export interface DesignOption {
  id: string;
  set_id: string;
  project_id: string;
  name: string;
  sort_order: number;
  source_document_id: string | null;
  bim_model_id: string | null;
  /** The bill of quantities paired to this option (the pricing target). */
  boq_id: string | null;
  match_session_id: string | null;
  /** The project schedule this option is dated by, when one is linked. */
  schedule_id: string | null;
  /** The carbon inventory this option is weighed by, when one is linked. */
  carbon_inventory_id: string | null;
  /** Where the bill came from: generated here from the model, or linked from
   *  an estimate the project already held. Empty while there is no bill. */
  boq_source: DesignOptionBoqSource;
  status: DesignOptionStatus;
  /** Human-readable failure reason when `status === 'failed'`. */
  error: string;
  /** Money fields, Decimal-as-string. */
  direct_cost: string;
  markups_total: string;
  grand_total: string;
  cost_per_m2: string;
  /** Duration read off the linked schedule, in days, Decimal-as-string. Zero
   *  when no schedule is linked - read `schedule_id` to tell the two apart. */
  duration_days: string;
  /** ISO finish date from the linked schedule, or '' when none is linked. */
  finish_date: string;
  /** Embodied carbon A1-A5 from the linked inventory, kgCO2e Decimal-as-string. */
  embodied_carbon_kg: string;
  /** The same figure over the gross floor area, kgCO2e/m2. */
  carbon_per_m2: string;
  /** Gross floor area used for the cost-per-area figure, Decimal-as-string. */
  gfa: string;
  gfa_unit: string;
  currency: string;
  element_count: number;
  position_count: number;
  breakdown: DesignOptionBreakdownRow[];
  validation_status: OptionValidationStatus;
  /** Validation score 0-1, Decimal-as-string, or null when not yet validated. */
  validation_score: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** A set of competing design options for one project. */
export interface DesignOptionSet {
  id: string;
  project_id: string;
  name: string;
  status: DesignOptionSetStatus;
  baseline_option_id: string | null;
  comparison_currency: string;
  decision_criteria: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  /** The set detail endpoint returns its options inline. */
  options?: DesignOption[];
}

/* ── Comparison contract ───────────────────────────────────────────────── */

/** Set-level fairness verdict for the comparison (drives the banner traffic
 *  light): 'ok' green, 'warnings' amber, 'error' red. */
export type FairnessStatus = 'ok' | 'warnings' | 'error';

/** Severity of a single fairness notice. */
export type FairnessSeverity = 'info' | 'warning' | 'error';

/**
 * One fairness notice on the comparison as a whole. `key` is an i18n key
 * (`designOptions.fairness.<name>`); `severity` drives the notice icon; `context`
 * carries interpolation values (a count, a currency code) for the localised text.
 */
export interface DesignOptionFairnessWarning {
  key: string;
  severity: FairnessSeverity;
  context: Record<string, unknown>;
}

/** One option column of the comparison, already rebased to the set currency. */
export interface DesignOptionColumn {
  option_id: string;
  name: string;
  direct_cost: string;
  markups_total: string;
  grand_total: string;
  /** Signed money delta versus the baseline option, Decimal-as-string. */
  delta_vs_baseline: string;
  /** Signed percentage delta versus the baseline, Decimal-as-string, or null
   *  when there is no baseline or the baseline total is zero (no meaningful %). */
  delta_pct: string | null;
  cost_per_m2: string;
  gfa: string;
  currency: string;
  element_count: number;
  position_count: number;
  validation_status: OptionValidationStatus;
  /** Whether the money was generated here or linked from the project. */
  boq_source: DesignOptionBoqSource;
  /**
   * Whether the option links a schedule at all. An option nobody has
   * programmed and one that finishes today both carry zero days, so this - not
   * the number - is what says the question was answered. Same for carbon.
   */
  has_programme: boolean;
  duration_days: string;
  finish_date: string;
  /** Signed day delta versus the baseline, or null when either side of the
   *  subtraction is unanswered. */
  delta_days_vs_baseline: string | null;
  has_carbon: boolean;
  /** Embodied carbon A1-A5, Decimal-as-string in `carbon_unit`. */
  embodied_carbon_kg: string;
  carbon_per_m2: string;
  carbon_unit: string;
  delta_carbon_vs_baseline: string | null;
}

/** One option's quantity and cost for a single trade row. */
export interface TradeDeltaPerOption {
  option_id: string;
  quantity: string;
  unit: string;
  cost: string;
}

/** One by-trade comparison row across every option. */
export interface TradeDeltaRow {
  key: string;
  label: string;
  /** Classification the row is grouped by, e.g. 'din276' | 'masterformat' | 'nrm' | 'trade'. */
  classification_system: string;
  baseline_quantity: string;
  baseline_cost: string;
  per_option: TradeDeltaPerOption[];
}

/** AI-suggested recommendation (human still confirms the decision). */
export interface DesignOptionRecommendation {
  option_id: string | null;
  /** The winner's relative margin over the runner-up, 0..1 Decimal-as-string: a
   *  clear winner reads high, a near tie reads near zero. Parse only for display. */
  confidence: string;
  reason_key: string;
}

/** Set-level fairness banner payload. */
export interface DesignOptionFairness {
  status: FairnessStatus;
  warnings: DesignOptionFairnessWarning[];
}

/** Full N-option comparison response. */
export interface DesignOptionComparisonResponse {
  set_id: string;
  set_name: string;
  comparison_currency: string;
  baseline_option_id: string | null;
  options: DesignOptionColumn[];
  by_trade: TradeDeltaRow[];
  recommendation: DesignOptionRecommendation;
  fairness: DesignOptionFairness;
}

/* ── Generate (dry-run preview + apply) ────────────────────────────────── */

/**
 * Result of generating a priced BOQ for an option. When `dry_run` is true the
 * server returns a preview only and applies nothing; the caller shows the
 * preview and the user confirms before a second call with `dry_run: false`
 * actually writes the matches to the option's BOQ (AI-augmented, human-confirmed).
 */
/**
 * One would-be (dry run) or applied BOQ line in a generate preview. Money and
 * quantity fields are Decimal-as-string; `section_path` is the hierarchical
 * section the line would land under.
 */
export interface DesignOptionGeneratePreviewLine {
  group_key: string;
  description: string;
  unit: string;
  quantity: string;
  unit_rate: string;
  currency: string;
  line_total: string;
  section_path: string[];
}

export interface DesignOptionGenerateResponse {
  option_id: string;
  dry_run: boolean;
  boq_id: string | null;
  method: string;
  status: DesignOptionStatus;
  positions_created: number;
  element_count: number;
  position_count: number;
  /** Element groups matched and, of those, auto/confirmed for apply. */
  groups_total: number;
  groups_confirmed: number;
  /** Money fields, Decimal-as-string. */
  direct_cost: string;
  markups_total: string;
  grand_total: string;
  cost_per_m2: string;
  gfa: string;
  gfa_unit: string;
  currency: string;
  /** True when the option's own bill mixes currencies (comparison stays honest). */
  is_mixed_currency: boolean;
  breakdown: DesignOptionBreakdownRow[];
  /** The would-be or applied lines; on a dry run nothing is persisted. */
  preview: DesignOptionGeneratePreviewLine[];
  warnings: string[];
}

/* ── Sets ──────────────────────────────────────────────────────────────── */

export function listOptionSets(projectId: string): Promise<DesignOptionSet[]> {
  return apiGet<DesignOptionSet[]>(
    `${BASE}/sets/?project_id=${encodeURIComponent(projectId)}`,
  );
}

export function getOptionSet(setId: string): Promise<DesignOptionSet> {
  return apiGet<DesignOptionSet>(`${BASE}/sets/${encodeURIComponent(setId)}`);
}

export function createOptionSet(body: {
  project_id: string;
  name: string;
}): Promise<DesignOptionSet> {
  return apiPost<DesignOptionSet>(`${BASE}/sets/`, body);
}

export function deleteOptionSet(setId: string): Promise<void> {
  return apiDelete(`${BASE}/sets/${encodeURIComponent(setId)}`);
}

export function setBaseline(
  setId: string,
  optionId: string,
): Promise<DesignOptionSet> {
  return apiPost<DesignOptionSet>(
    `${BASE}/sets/${encodeURIComponent(setId)}/baseline/`,
    { option_id: optionId },
  );
}

export function getComparison(
  setId: string,
): Promise<DesignOptionComparisonResponse> {
  return apiGet<DesignOptionComparisonResponse>(
    `${BASE}/sets/${encodeURIComponent(setId)}/comparison/`,
  );
}

/* ── Options ───────────────────────────────────────────────────────────── */

export function createOption(
  setId: string,
  body: { name: string },
): Promise<DesignOption> {
  return apiPost<DesignOption>(
    `${BASE}/sets/${encodeURIComponent(setId)}/options/`,
    body,
  );
}

export function deleteOption(optionId: string): Promise<void> {
  return apiDelete(`${BASE}/options/${encodeURIComponent(optionId)}`);
}

/** Link an already-imported BIM model to an option (no file upload). */
export function linkBimModel(
  optionId: string,
  bimModelId: string,
): Promise<DesignOption> {
  return apiPost<DesignOption>(
    `${BASE}/options/${encodeURIComponent(optionId)}/attach-model/`,
    { bim_model_id: bimModelId },
  );
}

/**
 * Link a project document (an uploaded CAD/BIM file) to an option.
 *
 * The BIM hub owns conversion. When the document already has a converted model
 * the server adopts it and the option reads `model_attached`; otherwise the
 * document is recorded and the option waits on the conversion.
 */
export function linkSourceDocument(
  optionId: string,
  documentId: string,
): Promise<DesignOption> {
  return apiPost<DesignOption>(
    `${BASE}/options/${encodeURIComponent(optionId)}/attach-model/`,
    { source_document_id: documentId },
  );
}

/**
 * Point an option at the estimate, programme and carbon inventory the project
 * already holds.
 *
 * Presence in the body decides what changes: omit a key to leave that reference
 * alone, send it as `null` to clear it. Linking a bill prices the option there
 * and then, with no model involved - which is how a hand-built option estimate
 * becomes a first-class option rather than something you have to regenerate.
 */
export function linkOptionReferences(
  optionId: string,
  body: {
    boq_id?: string | null;
    schedule_id?: string | null;
    carbon_inventory_id?: string | null;
  },
): Promise<DesignOption> {
  return apiPost<DesignOption>(
    `${BASE}/options/${encodeURIComponent(optionId)}/link/`,
    body,
  );
}

/* ── What the project already holds, for the link pickers ──────────────── */

/** One bill of quantities in the project, as the link picker lists it. */
export interface LinkableBoq {
  id: string;
  name: string;
  status: string;
  estimate_type?: string | null;
}

/** One schedule in the project, as the link picker lists it. */
export interface LinkableSchedule {
  id: string;
  name: string;
  status: string;
  start_date: string | null;
  end_date: string | null;
}

/** One carbon inventory in the project, as the link picker lists it. */
export interface LinkableCarbonInventory {
  id: string;
  name: string;
  scope: string;
  status: string;
}

export function listProjectBoqs(projectId: string): Promise<LinkableBoq[]> {
  return apiGet<LinkableBoq[]>(
    `/v1/boq/boqs/?project_id=${encodeURIComponent(projectId)}`,
  );
}

/**
 * The schedule list endpoint answers with a page envelope rather than a bare
 * array, so the items are unwrapped here and nowhere else.
 */
export async function listProjectSchedules(
  projectId: string,
): Promise<LinkableSchedule[]> {
  const page = await apiGet<Page<LinkableSchedule>>(
    `/v1/schedule/schedules/?project_id=${encodeURIComponent(projectId)}&limit=100`,
  );
  return page.items ?? [];
}

export function listProjectCarbonInventories(
  projectId: string,
): Promise<LinkableCarbonInventory[]> {
  return apiGet<LinkableCarbonInventory[]>(
    `/v1/carbon/inventories?project_id=${encodeURIComponent(projectId)}`,
  );
}

/**
 * Generate (or re-generate) the priced BOQ for an option.
 *
 * Pass `dryRun: true` first to fetch a preview that applies nothing, then
 * `dryRun: false` once the user confirms. The backend routes the option's
 * attached model through the match pipeline and totals the resulting BOQ.
 */
export function generateOption(
  optionId: string,
  dryRun: boolean,
): Promise<DesignOptionGenerateResponse> {
  return apiPost<DesignOptionGenerateResponse>(
    `${BASE}/options/${encodeURIComponent(optionId)}/generate/`,
    { dry_run: dryRun },
    // Conversion + matching can be heavy on a small box; opt into the long budget.
    { longRunning: true },
  );
}

/**
 * Download the comparison as an .xlsx file. Fetches with the Bearer token (the
 * JWT lives in the auth store, not a cookie) and triggers an anchor download,
 * so the sheet is never opened in a blank tab that silently 401s.
 */
export async function downloadComparisonXlsx(
  setId: string,
  filename: string,
): Promise<void> {
  const token = getAuthToken();
  const response = await fetch(
    `${API_BASE}${BASE}/sets/${encodeURIComponent(setId)}/comparison.xlsx`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!response.ok) {
    let detail = `Export failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore body parse errors and keep the status-based message
    }
    throw new Error(detail);
  }
  const blob = await response.blob();
  triggerDownload(blob, filename);
}
