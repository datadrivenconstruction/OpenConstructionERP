// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client for the Excel round-trip review: a dry run of an edited export that
 * lists what an import would change, before anything is written.
 *
 * Shapes mirror ``preview_boq_excel_import`` in
 * ``backend/app/modules/boq/router.py``. Numbers stay strings, exactly as the
 * server compared them.
 */
import { activeLanguageTag, extractErrorMessageFromBody, fetchWithAuth } from '@/shared/lib/api';

export type ReviewField = 'description' | 'unit' | 'ordinal' | 'quantity' | 'unit_rate' | 'classification';

export interface FieldChange {
  field: ReviewField | string;
  old: string | null;
  new: string | null;
}

export interface UpdatedRow {
  row: number;
  position_id: string;
  ordinal: string;
  changes: FieldChange[];
}

export interface ConflictRow extends UpdatedRow {
  stored_version: number;
  file_version: number | null;
}

export interface CreatedRow {
  row: number;
  ordinal: string;
  description: string;
}

export interface RemovedRow {
  position_id: string;
  ordinal: string;
  description: string;
}

export interface ReviewNote {
  row?: number;
  issue?: string;
  severity?: string;
  message?: string;
}

export interface ExcelReviewPreview {
  /** False when the sheet carries no Position ID: it imports as it always did. */
  round_trip: boolean;
  created: CreatedRow[];
  updated: UpdatedRow[];
  unchanged: number;
  would_delete: RemovedRow[];
  conflicts: ConflictRow[];
  problems: ReviewNote[];
  errors: { row?: number; error?: string }[];
  counts: {
    created: number;
    updated: number;
    unchanged: number;
    would_delete: number;
    conflicts: number;
  };
  truncated: Record<'created' | 'updated' | 'would_delete' | 'conflicts', boolean>;
  boq_version_token: string;
}

/** What the person decided for each row of the review. */
export interface ReviewChoices {
  /** Changed rows the person unticked: kept as they are in the app. */
  skipIds: string[];
  /** Stale rows where the person chose the Excel value. */
  acceptIds: string[];
  /** Missing rows the person ticked "Delete from BOQ" for. */
  deleteIds: string[];
}

export function isSpreadsheetName(fileName: string): boolean {
  return /\.(xlsx|csv)$/i.test(fileName);
}

/** Ask the server what importing ``file`` would change; nothing is written. */
export async function previewExcelChanges(boqId: string, file: File): Promise<ExcelReviewPreview> {
  const form = new FormData();
  form.append('file', file);
  const lang = activeLanguageTag();
  const res = await fetchWithAuth(`/api/v1/boq/boqs/${encodeURIComponent(boqId)}/import/excel/preview/`, {
    method: 'POST',
    headers: lang ? { 'Accept-Language': lang } : {},
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(extractErrorMessageFromBody(body) ?? String(res.status));
  }
  return (await res.json()) as ExcelReviewPreview;
}

/** Form fields the apply call (``/import/auto/``) takes for the person's choices. */
export function applyFields(choices: ReviewChoices): Record<string, string> {
  return {
    skip_position_ids: JSON.stringify(choices.skipIds),
    accept_position_ids: JSON.stringify(choices.acceptIds),
    delete_position_ids: JSON.stringify(choices.deleteIds),
  };
}

/** True when the review has anything to show: changes, new rows, removed rows or conflicts. */
export function hasReviewableChanges(preview: ExcelReviewPreview): boolean {
  const c = preview.counts;
  return preview.round_trip && c.created + c.updated + c.would_delete + c.conflicts > 0;
}
