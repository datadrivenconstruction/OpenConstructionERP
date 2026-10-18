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
  | 'manual';

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
}

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
