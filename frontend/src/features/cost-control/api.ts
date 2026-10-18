// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cost control API. Money arrives as decimal STRINGS and is only turned into a
// number for display and chart geometry, never for arithmetic that is sent back.
import { apiDelete, apiGet, apiPost, apiPut } from '@/shared/lib/api';

export type CostControlAxis = 'cost_line' | 'contract';

export type ForecastSource =
  | 'none'
  | 'budget'
  | 'estimate'
  | 'partly_awarded'
  | 'awarded'
  | 'measured'
  | 'final'
  | 'manual'
  /** The net invoiced amount, read by the maximum method. */
  | 'invoiced'
  /** Projected from progress and spend (earned value). */
  | 'evm';

/** How a project, or one line, reads its forecast. */
export const FORECAST_METHODS = ['best_available', 'maximum', 'evm_cpi', 'manual'] as const;
export type ForecastMethod = (typeof FORECAST_METHODS)[number];
/** The methods a line can be set to by choice; manual is set by entering an amount. */
export const LINE_METHODS = ['best_available', 'maximum', 'evm_cpi'] as const;
export type LineForecastMethod = (typeof LINE_METHODS)[number];
/** Where a line's method comes from: the project, the line's own choice, or a person's amount. */
export type MethodOrigin = 'project' | 'line' | 'manual';
export type SnapshotStatus = 'draft' | 'frozen';
export const EVIDENCE_KINDS = ['document', 'minutes', 'other'] as const;
export type EvidenceKind = (typeof EVIDENCE_KINDS)[number];

export type RowKind =
  | 'cost_line'
  | 'contract'
  | 'unassigned'
  | 'changes_without_contract'
  | 'other'
  | 'remaining'
  /** An account's own amount, planned on the account and not broken down into cost lines yet. */
  | 'allowance';

export const COST_STAGES = [
  'budget',
  'estimate',
  'detailed_estimate',
  'pre_tender',
  'award',
  'forecast',
  'final',
] as const;
export type CostStage = (typeof COST_STAGES)[number];

export interface ForecastOverride {
  id: string;
  amount: string;
  reason: string;
  document_ref: string;
  document_id: string | null;
  created_by: string | null;
  created_at: string | null;
  closed_at: string | null;
}

export interface CostControlRow {
  key: string;
  kind: RowKind;
  code: string;
  description: string;
  account_id: string | null;
  status: string;
  budget: string;
  estimate: string;
  planned: string;
  awarded: string;
  changes: string;
  committed: string;
  /** Quantity times contract rate of the measured work, apart from what is certified. */
  measured: string;
  certified: string;
  /** Net amount of supplier invoices on this line. */
  invoiced: string;
  paid: string;
  pending_changes: string;
  forecast: string;
  forecast_source: ForecastSource;
  automatic_forecast: string;
  automatic_source: ForecastSource;
  variance: string;
  variance_pct: string | null;
  override: ForecastOverride | null;
  forecast_method: ForecastMethod;
  method_origin: MethodOrigin;
  /** False when the chosen method had nothing to work with and the best available figure stands in. */
  method_applied: boolean;
  method_comment: string;
}

export interface CostControlAccount {
  id: string;
  code: string;
  name: string;
  /** The account's own title; empty when its code list has none, then `name` is shown. */
  title?: string;
  parent_id: string | null;
  level?: number;
  /** Money planned on the account itself (decimal string). */
  own_amount?: string;
}

export interface CostControlFinding {
  rule_id: string;
  severity: 'warning' | 'info';
  line_key: string | null;
  code: string;
  amount: string;
  details: Record<string, string>;
}

export interface SnapshotSummary {
  id: string;
  taken_on: string;
  stage: CostStage;
  label: string;
  note: string;
  currency: string;
  totals: Record<string, string>;
  created_by: string | null;
  created_at: string | null;
  status: SnapshotStatus;
  frozen_at: string | null;
  frozen_by: string | null;
  previous_snapshot_id: string | null;
  forecast_method: ForecastMethod;
  threshold_amount: string;
  threshold_pct: string | null;
}

export interface SnapshotPage {
  items: SnapshotSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface CostControlReport {
  project_id: string;
  currency: string;
  axis: CostControlAxis;
  as_of: string;
  totals: Record<string, string>;
  rows: CostControlRow[];
  accounts: CostControlAccount[];
  findings: CostControlFinding[];
  last_snapshot: SnapshotSummary | null;
  forecast_method: ForecastMethod;
}

export interface LineHistoryPoint {
  snapshot_id: string;
  taken_on: string;
  stage: CostStage;
  label: string;
  forecast: string;
  forecast_source: ForecastSource;
  committed: string;
  certified: string;
}

export interface LineChangeEvent {
  approved_on: string | null;
  source_kind: string;
  source_code: string;
  contract_code: string;
  amount: string;
}

export interface LineHistory {
  cost_line_id: string;
  code: string;
  description: string;
  currency: string;
  current: CostControlRow;
  snapshots: LineHistoryPoint[];
  changes: LineChangeEvent[];
  overrides: ForecastOverride[];
  project_method: ForecastMethod;
  method_choice: LineMethodChoice | null;
  /** The line read under every method, side by side. */
  methods: MethodOutcome[];
}

export interface MethodOutcome {
  method: ForecastMethod;
  amount: string;
  source: ForecastSource;
  applied: boolean;
  progress: string | null;
  cpi: string | null;
  earned: string | null;
  actual: string | null;
}

export interface LineMethodChoice {
  cost_line_id: string;
  method: LineForecastMethod;
  comment: string;
  updated_by: string | null;
  updated_at: string | null;
}

export interface LineMethodBody {
  method: LineForecastMethod;
  comment: string;
}

export interface CostControlSettings {
  project_id: string;
  forecast_method: ForecastMethod;
  evidence_threshold_amount: string;
  evidence_threshold_pct: string | null;
  is_default: boolean;
  updated_by: string | null;
  updated_at: string | null;
}

export interface CostControlSettingsBody {
  forecast_method: ForecastMethod;
  evidence_threshold_amount: string;
  evidence_threshold_pct: string | null;
}

/** A V19, V20 or V22 finding, already in the reader's language. */
export interface ForecastFinding {
  rule_id: string;
  rule_number: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  suggestion: string;
  element_ref: string | null;
  details: Record<string, string>;
}

export interface ForecastPanel {
  project_id: string;
  currency: string;
  settings: CostControlSettings;
  method_counts: Record<string, number>;
  fallback_lines: number;
  line_choices: number;
  manual_lines: number;
  open_draft: SnapshotSummary | null;
  findings: ForecastFinding[];
}

export interface EvidenceItem {
  kind: EvidenceKind;
  ref: string;
  document_id: string | null;
}

export interface SnapshotLine {
  key: string;
  kind: string;
  code: string;
  description: string;
  source: ForecastSource;
  method: ForecastMethod;
  forecast: string;
  committed: string;
  previous: string | null;
  delta: string;
  delta_pct: string | null;
  needs_evidence: boolean;
  documented: boolean;
  comment: string;
  evidence: EvidenceItem[];
  note_updated_at: string | null;
}

export interface SnapshotDetail extends SnapshotSummary {
  lines: SnapshotLine[];
  previous: SnapshotSummary | null;
  findings: ForecastFinding[];
}

export interface SnapshotNoteBody {
  comment: string;
  evidence: { kind: EvidenceKind; ref: string; document_id?: string | null }[];
}

export interface ComparisonColumn {
  id: string | null;
  taken_on: string;
  stage: string;
  label: string;
  status: SnapshotStatus | 'live';
  total: string;
}

export interface ComparisonRow {
  key: string;
  code: string;
  description: string;
  kind: string;
  values: (string | null)[];
  delta: string;
  delta_pct: string | null;
}

export interface SnapshotMatrix {
  project_id: string;
  currency: string;
  columns: ComparisonColumn[];
  rows: ComparisonRow[];
}

export type LadderCause = 'new' | 'removed' | 'method' | 'source' | 'value';

export interface LadderStep {
  key: string;
  code: string;
  description: string;
  kind: string;
  before: string | null;
  after: string | null;
  delta: string;
  cause: LadderCause;
  source_before: string;
  source_after: string;
  method_before: string;
  method_after: string;
  comment: string;
  evidence: EvidenceItem[];
}

export interface DeltaLadder {
  project_id: string;
  currency: string;
  start_column: ComparisonColumn;
  end_column: ComparisonColumn;
  start: string;
  end: string;
  steps: LadderStep[];
  other: string;
  other_count: number;
}

export const PHASE_LAYERS = [
  'budget',
  'estimate',
  'tender',
  'awarded',
  'changes',
  'committed',
  'pending',
  'measured',
  'certified',
  'invoiced',
  'paid',
  'forecast',
] as const;
export type PhaseLayer = (typeof PHASE_LAYERS)[number];

export interface PhaseRow {
  key: string;
  kind: 'account' | 'cost_line' | 'allowance' | 'unassigned';
  account_id: string | null;
  parent_key: string | null;
  level: number;
  code: string;
  description: string;
  values: Record<PhaseLayer, string>;
  pct: Record<PhaseLayer, string | null>;
  progress_pct: string | null;
  invoiced_pct: string | null;
}

export interface PhaseComparison {
  project_id: string;
  currency: string;
  as_of: string;
  layers: PhaseLayer[];
  rows: PhaseRow[];
  totals: PhaseRow;
}

export const EXPORT_KINDS = ['cost_report', 'phase_comparison', 'invoice_ledger', 'forecast_documentation'] as const;
export type ExportKind = (typeof EXPORT_KINDS)[number];

export interface SnapshotCreate {
  stage: CostStage;
  label: string;
  note: string;
}

export interface ForecastOverrideCreate {
  amount: string;
  reason: string;
  document_ref: string;
}

/** Rows that can be put on a cost line from cost control. */
export type AssignKind = 'contract_line' | 'po_item' | 'contract' | 'change_order_item' | 'invoice_line';

export interface UnassignedItem {
  kind: AssignKind;
  id: string;
  group_id: string;
  group_code: string;
  group_title: string;
  code: string;
  description: string;
  amount: string;
}

export interface UnassignedPage {
  items: UnassignedItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface AssignBody {
  cost_line_id: string;
  items: { kind: AssignKind; id: string }[];
  /** Needed when a row inherits another cost line; kept on the row with who and when. */
  reason?: string;
}

/* ── The chain: suspense buckets, rules V6 to V10 and V15, their fixes ── */

export interface SuspenseItem {
  kind: AssignKind;
  id: string;
  group_id: string;
  group_code: string;
  group_title: string;
  code: string;
  description: string;
  amount: string;
  can_inherit: boolean;
}

export interface SuspenseBucket {
  kind: AssignKind;
  count: number;
  amount: string;
  inheritable: number;
  /** True when this money is in the report's "not on any cost line" row. */
  in_report: boolean;
  items: SuspenseItem[];
}

export interface ChainFinding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  /** Already in the reader's language. */
  message: string;
  suggestion: string;
  element_ref: string | null;
  details: Record<string, string>;
}

export interface ChainReport {
  project_id: string;
  currency: string;
  buckets: SuspenseBucket[];
  findings: ChainFinding[];
}

export type VectorMode = 'set' | 'inherit' | 'clear';

export interface SetVectorBody {
  kind: AssignKind;
  id: string;
  mode: VectorMode;
  cost_line_id?: string | null;
  reason?: string;
}

export interface SetVectorResult {
  cost_line_id: string | null;
  source: string | null;
  override: boolean;
}

export interface InheritResult {
  contract_line: number;
  change_order_item: number;
  invoice_line: number;
}

export interface DirectCostResult {
  contract_id: string;
  contract_code: string;
  contract_line_id: string | null;
}

export const costControlApi = {
  report: (projectId: string, axis: CostControlAxis) =>
    apiGet<CostControlReport>(`/v1/costmodel/projects/${projectId}/cost-control/?axis=${axis}`),
  snapshots: (projectId: string) =>
    apiGet<SnapshotPage>(`/v1/costmodel/projects/${projectId}/cost-control/snapshots/`),
  createSnapshot: (projectId: string, body: SnapshotCreate) =>
    apiPost<SnapshotSummary, SnapshotCreate>(`/v1/costmodel/projects/${projectId}/cost-control/snapshots/`, body),
  deleteSnapshot: (snapshotId: string) => apiDelete(`/v1/costmodel/cost-control/snapshots/${snapshotId}/`),
  setForecast: (lineId: string, body: ForecastOverrideCreate) =>
    apiPut<ForecastOverride, ForecastOverrideCreate>(`/v1/costmodel/cost-control/lines/${lineId}/forecast/`, body),
  clearForecast: (lineId: string) => apiDelete(`/v1/costmodel/cost-control/lines/${lineId}/forecast/`),
  lineHistory: (lineId: string) => apiGet<LineHistory>(`/v1/costmodel/cost-control/lines/${lineId}/history/`),
  settings: (projectId: string) =>
    apiGet<CostControlSettings>(`/v1/costmodel/projects/${projectId}/cost-control/settings/`),
  saveSettings: (projectId: string, body: CostControlSettingsBody) =>
    apiPut<CostControlSettings, CostControlSettingsBody>(
      `/v1/costmodel/projects/${projectId}/cost-control/settings/`,
      body,
    ),
  forecastPanel: (projectId: string) =>
    apiGet<ForecastPanel>(`/v1/costmodel/projects/${projectId}/cost-control/forecast/`),
  setLineMethod: (lineId: string, body: LineMethodBody) =>
    apiPut<LineMethodChoice, LineMethodBody>(`/v1/costmodel/cost-control/lines/${lineId}/method/`, body),
  clearLineMethod: (lineId: string) => apiDelete(`/v1/costmodel/cost-control/lines/${lineId}/method/`),
  snapshot: (snapshotId: string) => apiGet<SnapshotDetail>(`/v1/costmodel/cost-control/snapshots/${snapshotId}/`),
  putNote: (snapshotId: string, rowKey: string, body: SnapshotNoteBody) =>
    apiPut<SnapshotLine, SnapshotNoteBody>(
      `/v1/costmodel/cost-control/snapshots/${snapshotId}/notes/${encodeURIComponent(rowKey)}/`,
      body,
    ),
  refreshSnapshot: (snapshotId: string) =>
    apiPost<SnapshotSummary, Record<string, never>>(`/v1/costmodel/cost-control/snapshots/${snapshotId}/refresh/`, {}),
  freezeSnapshot: (snapshotId: string) =>
    apiPost<SnapshotSummary, Record<string, never>>(`/v1/costmodel/cost-control/snapshots/${snapshotId}/freeze/`, {}),
  compare: (projectId: string) =>
    apiGet<SnapshotMatrix>(`/v1/costmodel/projects/${projectId}/cost-control/compare/`),
  ladder: (projectId: string, start: string, end: string) =>
    apiGet<DeltaLadder>(
      `/v1/costmodel/projects/${projectId}/cost-control/ladder/?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
    ),
  phases: (projectId: string) =>
    apiGet<PhaseComparison>(`/v1/costmodel/projects/${projectId}/cost-control/phases/`),
  unassigned: (projectId: string) =>
    apiGet<UnassignedPage>(`/v1/costmodel/projects/${projectId}/cost-control/unassigned/`),
  assign: (projectId: string, body: AssignBody) =>
    apiPost<{ assigned: number }, AssignBody>(`/v1/costmodel/projects/${projectId}/cost-control/assign/`, body),
  chain: (projectId: string) => apiGet<ChainReport>(`/v1/costmodel/projects/${projectId}/cost-control/chain/`),
  setVector: (projectId: string, body: SetVectorBody) =>
    apiPut<SetVectorResult, SetVectorBody>(`/v1/costmodel/projects/${projectId}/cost-control/vectors/`, body),
  inheritAll: (projectId: string) =>
    apiPost<InheritResult, Record<string, never>>(`/v1/costmodel/projects/${projectId}/cost-control/inherit/`, {}),
  directCost: (projectId: string, invoiceId: string, costLineId: string) =>
    apiPost<DirectCostResult, { cost_line_id: string }>(
      `/v1/costmodel/projects/${projectId}/cost-control/invoices/${invoiceId}/direct-contract/`,
      { cost_line_id: costLineId },
    ),
};

/** Money string to number for display and geometry only. */
export function num(value: string | null | undefined): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}
