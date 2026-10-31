// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the measurement book (/v1/measurement-book): dated quantity entries per BOQ
 * position, a second-person check, the running bill and the hand-over to progress claims.
 * Quantities and money arrive and leave as decimal strings.
 */
import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

export type CheckStatus = 'unchecked' | 'checked' | 'disputed';

export interface MeasurementEntry {
  id: string;
  project_id: string;
  boq_position_id: string;
  entry_date: string;
  location: string | null;
  description: string | null;
  length: string | null;
  breadth: string | null;
  height: string | null;
  number: string | null;
  direct_quantity: string | null;
  quantity: string;
  measured_by: string | null;
  check_status: CheckStatus;
  check_quantity: string | null;
  checked_by: string | null;
  checked_at: string | null;
  bill_ref: string | null;
  notes: string | null;
}

export interface EntryInput {
  project_id: string;
  boq_position_id: string;
  entry_date: string;
  location?: string;
  description?: string;
  length?: string;
  breadth?: string;
  height?: string;
  number?: string;
  direct_quantity?: string;
  measured_by?: string;
  notes?: string;
}

export interface PositionSummary {
  boq_position_id: string;
  ordinal: string;
  description: string;
  unit: string;
  boq_quantity: string;
  unit_rate: string;
  measured_quantity: string;
  checked_quantity: string;
  entry_count: number;
  unchecked_count: number;
  percent_measured: string;
  value_to_date: string;
}

export interface RunningBill {
  project_id: string;
  lines: PositionSummary[];
  total_value: string;
  unchecked_count: number;
  can_certify: boolean;
  currency: string;
}

export interface ValidationResult {
  rule_id: string;
  severity: string;
  passed: boolean;
  message: string;
  element_ref: string | null;
}

export interface ValidationReport {
  status: string;
  results: ValidationResult[];
}

export const fetchEntries = (projectId: string, positionId: string) =>
  apiGet<MeasurementEntry[]>(`/v1/measurement-book/entries/?project_id=${projectId}&boq_position_id=${positionId}`);
export const createEntry = (body: EntryInput) => apiPost<MeasurementEntry>(`/v1/measurement-book/entries/`, body);
export const updateEntry = (id: string, body: Partial<EntryInput>) =>
  apiPatch<MeasurementEntry>(`/v1/measurement-book/entries/${id}`, body);
export const deleteEntry = (id: string) => apiDelete(`/v1/measurement-book/entries/${id}`);
export const checkEntry = (
  id: string,
  body: { status: CheckStatus; check_quantity?: string; checked_by?: string },
) => apiPost<MeasurementEntry>(`/v1/measurement-book/entries/${id}/check`, body);

export const fetchPositions = (projectId: string) =>
  apiGet<PositionSummary[]>(`/v1/measurement-book/positions/?project_id=${projectId}`);
export const fetchRunningBill = (projectId: string) =>
  apiGet<RunningBill>(`/v1/measurement-book/running-bill/?project_id=${projectId}`);
export const postToProgress = (projectId: string, periodLabel: string) =>
  apiPost<{ recorded: number; skipped: number }>(`/v1/measurement-book/running-bill/post-to-progress?project_id=${projectId}`, {
    period_label: periodLabel,
  });
export const fetchValidation = (projectId: string, deviationThresholdPct = 5) =>
  apiGet<ValidationReport>(
    `/v1/measurement-book/validation/?project_id=${projectId}&deviation_threshold_pct=${deviationThresholdPct}`,
  );
