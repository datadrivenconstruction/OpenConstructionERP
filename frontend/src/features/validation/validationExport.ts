// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for the validation findings export (CSV / XLSX).
 *
 * The actual file bytes are produced server-side by the validation module
 * (`GET /v1/validation/reports/{id}/export.csv|.xlsx`), which is the only
 * place formula-injection neutralisation is enforced. These helpers just
 * derive the request path and a friendly download filename, kept pure so
 * they are unit-testable without a browser or network.
 */

export type ValidationExportFormat = 'csv' | 'xlsx';

/** MIME type the browser should treat each export blob as. */
export const VALIDATION_EXPORT_MEDIA: Record<ValidationExportFormat, string> = {
  csv: 'text/csv;charset=utf-8;',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
};

/**
 * API path (relative to the `/api` mount) for downloading a report export.
 *
 * @param reportId Persisted ValidationReport id.
 * @param format   `csv` or `xlsx`.
 */
export function validationExportPath(reportId: string, format: ValidationExportFormat): string {
  return `/api/v1/validation/reports/${encodeURIComponent(reportId)}/export.${format}`;
}

/**
 * Suggested client-side download filename for a report export.
 *
 * Uses the BOQ (target) id when available - the same value the user picks in
 * the BOQ dropdown - shortened for readability, falling back to the report id
 * and then a constant. Only `[A-Za-z0-9_-]` is kept so the name is safe on
 * every OS.
 */
export function validationExportFilename(
  format: ValidationExportFormat,
  opts: { boqId?: string | null; reportId?: string | null } = {},
): string {
  const raw = (opts.boqId || opts.reportId || '').trim();
  const cleaned = raw.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 12);
  const base = cleaned || 'report';
  return `validation_findings_${base}.${format}`;
}
