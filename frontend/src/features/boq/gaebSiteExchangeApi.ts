// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client for the GAEB site phases: X31 measured quantities and X89 invoices.
 *
 * Shapes mirror ``backend/app/modules/boq/gaeb_exchange_router.py``. Money and
 * quantities are decimal strings on the wire and stay strings here, so a
 * figure is shown exactly as the server computed it.
 */
import {
  apiGet,
  apiPost,
  extractErrorMessageFromBody,
  fetchWithAuth,
  triggerDownload,
} from '@/shared/lib/api';

const BOQ_BASE = '/api/v1/boq/boqs';
const CLAIM_BASE = '/api/v1/boq/claims';

export interface X31MatchedItem {
  oz: string;
  quantity: string | null;
  row_count: number;
  rows: string[];
  position_id: string;
  ordinal: string;
  description: string;
  unit: string;
  matched_via: string;
  current_quantity: string;
  current_measured_quantity: string | null;
  proposed_quantity: string;
  difference_to_quantity: string;
  unchanged: boolean;
}

export interface X31UnmatchedItem {
  oz: string;
  quantity: string | null;
  row_count: number;
  reason: string;
  candidates?: string[];
}

export interface X31Preview {
  file_name: string;
  method: string;
  project_name: string;
  boq_name: string;
  items_in_file: number;
  matched: X31MatchedItem[];
  unmatched: X31UnmatchedItem[];
  positions_not_in_file: number;
}

export interface X31ApplyResult {
  applied: string[];
  unchanged: string[];
  errors: { position_id: string; error: string }[];
  set_boq_quantity: boolean;
}

export interface X89CheckLine {
  oz: string;
  description: string;
  unit: string;
  bill_qty: string | null;
  unit_price: string | null;
  amount: string;
  position_id: string | null;
  expected_amount: string | null;
  difference: string;
  issues: string[];
}

export interface X89TotalsCheck {
  key: string;
  stated: string | null;
  computed: string;
  matches: boolean;
}

export interface X89CheckReport {
  file_name: string;
  header: Record<string, string>;
  currency: string;
  items_in_file: number;
  lines: X89CheckLine[];
  invoiced_total: string;
  expected_total: string;
  total_difference: string;
  issue_counts: Record<string, number>;
  totals_check: X89TotalsCheck[];
  positions_not_invoiced: number;
}

export interface InvoiceParty {
  name: string;
  street: string;
  postcode: string;
  city: string;
  country: string;
  tax_no: string;
  vat_id: string;
}

export interface ClaimInvoicePreview {
  claim_id: string;
  claim_number: string;
  contract_code: string;
  invoice_type: string;
  invoice_date: string | null;
  period_start: string | null;
  period_end: string | null;
  currency: string;
  line_count: number;
  figures: {
    net: string;
    vat_rate: string;
    vat_amount: string;
    gross: string;
    retention: string;
    payable: string;
  };
  vat_source: string;
  creator: InvoiceParty;
  recipient: InvoiceParty;
  missing: string[];
  warnings: { code: string; detail: string }[];
}

async function failure(res: Response, fallback: string): Promise<Error> {
  const body = await res.json().catch(() => null);
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (detail && typeof detail === 'object' && 'message' in detail) {
      return new Error(String((detail as { message: unknown }).message));
    }
  }
  return new Error(extractErrorMessageFromBody(body) ?? fallback);
}

async function upload<T>(url: string, file: File): Promise<T> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetchWithAuth(url, { method: 'POST', body: form });
  if (!res.ok) throw await failure(res, `Upload failed (${res.status})`);
  return (await res.json()) as T;
}

/** Read an X31 and get proposals per OZ. Writes nothing. */
export function previewX31(boqId: string, file: File): Promise<X31Preview> {
  return upload<X31Preview>(`${BOQ_BASE}/${encodeURIComponent(boqId)}/import/gaeb-x31/preview/`, file);
}

/** Write the proposals a person confirmed. */
export function applyX31(
  boqId: string,
  body: {
    file_name: string;
    set_boq_quantity: boolean;
    items: { position_id: string; quantity: string; oz: string; rows: string[] }[];
  },
): Promise<X31ApplyResult> {
  return apiPost<X31ApplyResult>(`/v1/boq/boqs/${encodeURIComponent(boqId)}/import/gaeb-x31/apply/`, body);
}

/** Download the bill's measured quantities (or bill quantities) as X31. */
export async function downloadX31(
  boqId: string,
  basis: 'measured' | 'quantity',
  fallbackName: string,
): Promise<{ written: number; skipped: number }> {
  const res = await fetchWithAuth(
    `${BOQ_BASE}/${encodeURIComponent(boqId)}/export/gaeb-x31/?basis=${basis}`,
  );
  if (!res.ok) throw await failure(res, `Export failed (${res.status})`);
  const blob = await res.blob();
  triggerDownload(blob, `${fallbackName}.X31`);
  return {
    written: Number(res.headers.get('X-GAEB-Written') ?? '0') || 0,
    skipped: Number(res.headers.get('X-GAEB-Skipped') ?? '0') || 0,
  };
}

/** Check a received X89 against the bill. Writes nothing. */
export function checkX89(boqId: string, file: File): Promise<X89CheckReport> {
  return upload<X89CheckReport>(`${BOQ_BASE}/${encodeURIComponent(boqId)}/check/gaeb-x89/`, file);
}

function claimQuery(vatRate: string): string {
  const trimmed = vatRate.trim().replace(',', '.');
  return trimmed ? `?vat_rate=${encodeURIComponent(trimmed)}` : '';
}

/** What the X89 of a progress claim will say, and what it still lacks. */
export function previewClaimInvoice(claimId: string, vatRate = ''): Promise<ClaimInvoicePreview> {
  return apiGet<ClaimInvoicePreview>(
    `/v1/boq/claims/${encodeURIComponent(claimId)}/gaeb-x89/preview/${claimQuery(vatRate)}`,
  );
}

/** Download the X89 of a progress claim. */
export async function downloadClaimInvoice(claimId: string, fallbackName: string, vatRate = ''): Promise<void> {
  const res = await fetchWithAuth(
    `${CLAIM_BASE}/${encodeURIComponent(claimId)}/export/gaeb-x89/${claimQuery(vatRate)}`,
  );
  if (!res.ok) throw await failure(res, `Export failed (${res.status})`);
  const blob = await res.blob();
  triggerDownload(blob, `${fallbackName}.X89`);
}
