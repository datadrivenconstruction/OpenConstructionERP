// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client for exchange fidelity reports: what an import or export did not
 * carry across unchanged.
 *
 * Shapes mirror ``backend/app/modules/boq/exchange_fidelity.py`` and
 * ``exchange_fidelity_router.py``. Values stay strings, exactly as the server
 * read or wrote them.
 */
import { apiGet, apiPost, activeLanguageTag, fetchWithAuth, triggerDownload } from '@/shared/lib/api';

export type FidelitySeverity = 'error' | 'warning' | 'info';

export const FIDELITY_SEVERITIES: FidelitySeverity[] = ['error', 'warning', 'info'];

export const FIDELITY_KINDS = [
  'unsupported_element',
  'truncated_text',
  'altered_text',
  'rounded_value',
  'value_out_of_range',
  'dropped_attribute',
  'unmapped_unit',
  'lost_hierarchy',
  'markup_not_representable',
  'attachment_skipped',
  'changed_identifier',
  'exceeds_limit',
  'rejected_row',
  'skipped_row',
  'parser_warning',
  'roundtrip_mismatch',
] as const;

export type FidelityKind = (typeof FIDELITY_KINDS)[number];

export interface FidelityItem {
  severity: FidelitySeverity;
  kind: string;
  field: string;
  position_ref: string;
  position_id: string | null;
  original: string | null;
  written: string | null;
  count: number;
  detail: string;
  params: Record<string, unknown>;
}

export interface FidelitySummary {
  total: number;
  by_severity: Record<FidelitySeverity, number>;
  by_kind: Record<string, number>;
  critical: number;
  lossless: boolean;
  items_truncated?: boolean;
}

/** A report as an import or a check returns it, stored or not (``id`` null when not). */
export interface FidelityReport {
  id?: string | null;
  direction: 'import' | 'export';
  format_id: string;
  variant: string;
  roundtrip: boolean;
  is_check?: boolean;
  file_name?: string;
  created_at?: string | null;
  summary: FidelitySummary;
  items: FidelityItem[];
  items_truncated?: boolean;
}

export type FidelityReportListItem = Omit<FidelityReport, 'items'> & { id: string };

export type CheckFormat = 'gaeb_xml' | 'bc3' | 'excel' | 'csv';

const base = (boqId: string) => `/v1/boq/boqs/${encodeURIComponent(boqId)}/exchange-reports`;

export function listFidelityReports(boqId: string, direction?: 'import' | 'export'): Promise<{ items: FidelityReportListItem[] }> {
  const query = direction ? `?direction=${direction}` : '';
  return apiGet<{ items: FidelityReportListItem[] }>(`${base(boqId)}/${query}`);
}

export function getFidelityReport(boqId: string, reportId: string): Promise<FidelityReport> {
  return apiGet<FidelityReport>(`${base(boqId)}/${encodeURIComponent(reportId)}/`);
}

export function checkExportFidelity(
  boqId: string,
  body: { format_id: CheckFormat; variant?: '' | 'x83' | 'x84'; roundtrip: boolean },
): Promise<FidelityReport> {
  return apiPost<FidelityReport>(`${base(boqId)}/check/`, body);
}

/** Download a stored report as CSV or XLSX, narrowed to the dialog's filter. */
export async function downloadFidelityReport(
  boqId: string,
  reportId: string,
  format: 'csv' | 'xlsx',
  filter: { severity?: FidelitySeverity | ''; kind?: string },
): Promise<void> {
  const params = new URLSearchParams({ format });
  if (filter.severity) params.set('severity', filter.severity);
  if (filter.kind) params.set('kind', filter.kind);
  const language = activeLanguageTag();
  const res = await fetchWithAuth(
    `/api${base(boqId)}/${encodeURIComponent(reportId)}/download/?${params.toString()}`,
    { headers: language ? { 'Accept-Language': language } : {} },
  );
  if (!res.ok) throw new Error(String(res.status));
  const disposition = res.headers.get('Content-Disposition') ?? '';
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const name = match ? decodeURIComponent(match[1] ?? '') : `fidelity-report.${format}`;
  triggerDownload(await res.blob(), name);
}

/** Header an export response names its stored report in. */
export const REPORT_HEADER = 'X-Exchange-Report-Id';
/** Header with the report's ``errors,warnings,notes`` counts. */
export const COUNTS_HEADER = 'X-Exchange-Fidelity';

/** What an export response says about its report, or null when it says nothing. */
export function reportFromHeaders(headers: Headers): { id: string | null; errors: number; warnings: number; notes: number } | null {
  const counts = headers.get(COUNTS_HEADER);
  if (!counts) return null;
  const [errors, warnings, notes] = counts.split(',').map((n) => Number(n) || 0);
  return { id: headers.get(REPORT_HEADER), errors: errors ?? 0, warnings: warnings ?? 0, notes: notes ?? 0 };
}
