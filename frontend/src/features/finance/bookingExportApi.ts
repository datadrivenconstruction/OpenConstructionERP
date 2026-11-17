// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for booking export batches, backed by /api/v1/finance/booking-exports/
 * (backend/app/modules/finance/booking_router.py). Amounts are decimal strings.
 */

import { API_BASE, apiGet, apiPost, fetchWithAuth, triggerDownload, type Page } from '@/shared/lib/api';

export interface BookingFinding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  invoice: string;
  details: Record<string, unknown>;
}

export interface BookingPreview {
  invoices: number;
  rows: number;
  total: string;
  findings: BookingFinding[];
  blocked: boolean;
}

export interface BookingBatch {
  id: string;
  number: number;
  connector_type: string;
  period_from: string;
  period_to: string;
  reexport: boolean;
  invoice_count: number;
  row_count: number;
  total_amount: string;
  filename: string;
  sha256: string;
  created_at: string;
}

const BASE = '/v1/finance/booking-exports';

/** Connector types whose files are produced as booking batches rather than synced. */
export const BOOKING_CONNECTOR_TYPES: readonly string[] = ['booking_csv', 'datev_extf'];

export interface BookingRequest {
  connector_config_id: string;
  period_from: string;
  period_to: string;
  reexport: boolean;
}

export const previewBooking = (body: BookingRequest) => apiPost<BookingPreview>(`${BASE}/preview/`, body);
export const createBooking = (body: BookingRequest) => apiPost<BookingBatch>(`${BASE}/`, body);
export const listBookingBatches = () => apiGet<Page<BookingBatch>>(`${BASE}/`);

export async function downloadBookingBatch(batch: BookingBatch): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}${BASE}/${batch.id}/file`);
  if (!res.ok) throw new Error(res.statusText);
  triggerDownload(await res.blob(), batch.filename);
}

/** First and last day of the previous calendar month, as ISO dates. */
export function previousMonth(today: Date): { from: string; to: string } {
  const first = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  const last = new Date(today.getFullYear(), today.getMonth(), 0);
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return { from: iso(first), to: iso(last) };
}
