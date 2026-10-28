// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sheet-completeness API client (item #46).
 *
 * Reconciles the project's uploaded drawing sheets against a drawing index /
 * issue register and returns the gaps (missing / extra / revision mismatch) as
 * a validation report. The backend persists a `target_type="document"` report
 * under the `sheet_completeness` rule set, so past results are read back through
 * the standard `/v1/validation/reports/` endpoints.
 */

import { apiPost } from '@/shared/lib/api';

export interface ExpectedSheetIn {
  sheet_number: string;
  sheet_title?: string;
  revision?: string;
}

export interface SheetCompletenessRequest {
  project_id: string;
  /** An already-uploaded index PDF to parse the sheet list from. */
  index_document_id?: string;
  /** 1-based page of the index PDF; omit to scan every page. */
  index_page?: number;
  /** A pasted sheet list (CSV / TSV / one number per line). */
  pasted_index?: string;
  /** A structured expected-sheet list (skips parsing entirely). */
  expected_sheets?: ExpectedSheetIn[];
  /** Diff against current sheets only (default true). */
  current_only?: boolean;
}

export interface SheetRevisionMismatchItem {
  sheet_number: string;
  expected_rev: string;
  actual_rev: string;
}

/** The reconciliation snapshot (missing / extra / matched / revision drift). */
export interface SheetCompletenessSummary {
  index_source: 'document' | 'pasted';
  index_document_id?: string | null;
  index_page?: number | null;
  expected_count: number;
  actual_count: number;
  missing: string[];
  extra: string[];
  matched: string[];
  rev_mismatch: SheetRevisionMismatchItem[];
}

export interface SheetCompletenessResultItem {
  rule_id: string;
  status: string;
  message: string;
  element_ref?: string | null;
  details?: Record<string, unknown> | null;
  suggestion?: string | null;
}

export interface SheetCompletenessResponse {
  report_id: string;
  status: string;
  score: number | null;
  total_rules: number;
  passed_count: number;
  warning_count: number;
  error_count: number;
  info_count: number;
  rule_sets: string[];
  duration_ms: number;
  results: SheetCompletenessResultItem[];
  completeness: SheetCompletenessSummary;
}

/**
 * A persisted validation report as returned by `/v1/validation/reports/`. Only
 * the fields the panel reads are typed; the reconciliation snapshot lives under
 * `metadata.sheet_completeness` so a report can be restored without re-parsing.
 */
export interface StoredValidationReport {
  id: string;
  target_type: string;
  rule_set: string;
  status: string;
  score: string | null;
  created_at?: string | null;
  metadata?: {
    sheet_completeness?: SheetCompletenessSummary;
  } | null;
}

/** Run a sheet-completeness check and persist a document validation report. */
export async function checkSheetCompleteness(
  body: SheetCompletenessRequest,
): Promise<SheetCompletenessResponse> {
  return apiPost<SheetCompletenessResponse, SheetCompletenessRequest>(
    '/v1/documents/sheets/check-completeness/',
    body,
  );
}
