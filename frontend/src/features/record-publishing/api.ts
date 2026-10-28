// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Record Publishing module.
 *
 * One-tap "publish a record and distribute it": render a project record (the
 * daily site diary first, meetings and inspections next) as a single signed
 * PDF and send it as an acknowledged transmittal to a named set of recipients.
 *
 * Backed by /api/v1/record-publishing/ — see
 * backend/app/modules/record_publishing/router.py
 */

import {
  apiGet,
  apiPost,
  getAuthToken,
  triggerDownload,
} from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** Record kinds that can currently be published (extends over time). */
export type RecordKind = 'daily_diary' | 'meeting';

export interface PublishRecipientInput {
  email: string;
  display_name?: string | null;
  role?: string | null;
}

export interface PublishRecordRequest {
  source_kind: RecordKind;
  source_id: string;
  recipients: PublishRecipientInput[];
  /** Optional saved distribution list whose members are merged server-side. */
  distribution_list_id?: string | null;
  /** Transmittal reason. Defaults to "for_record" on the server. */
  reason_code?: string | null;
  notes?: string | null;
  /** Locale for the rendered cover sheet, e.g. the current UI language. */
  locale?: string | null;
}

export interface PublishedRecipientOut {
  email: string;
  display_name?: string | null;
  role?: string | null;
  /** Public link a recipient opens to acknowledge receipt (no login). */
  acknowledge_url: string;
  /** Public link a recipient opens to download the record PDF (no login). */
  record_url: string;
}

export interface PublishRecordResponse {
  transmittal_id: string;
  transmittal_number: string;
  subject: string;
  source_kind: string;
  source_id: string;
  project_id: string;
  record_filename: string;
  cover_sheet_path: string;
  recipient_count: number;
  recipients: PublishedRecipientOut[];
}

export interface SupportedKindsResponse {
  kinds: string[];
}

/* ── Calls ─────────────────────────────────────────────────────────────── */

/** List the record kinds the server can publish right now. */
export function supportedRecordKinds(): Promise<SupportedKindsResponse> {
  return apiGet<SupportedKindsResponse>('/v1/record-publishing/kinds/');
}

/**
 * Render a record as a PDF and distribute it with acknowledgement in one call.
 *
 * Project access is enforced server-side against the record's own project, so
 * a caller cannot publish a record from a project they cannot reach. The
 * response carries, per recipient, the record download URL and the
 * acknowledgement URL to forward.
 */
export function publishRecord(
  data: PublishRecordRequest,
): Promise<PublishRecordResponse> {
  return apiPost<PublishRecordResponse>('/v1/record-publishing/publish/', data);
}

/**
 * Download an already-published record PDF as an authenticated project member.
 *
 * Hits GET /api/v1/record-publishing/{transmittal_id}/record.pdf with the
 * stored bearer token, then streams the response to the browser as a file.
 * Mirrors the blob-download pattern used by the diary PDF export.
 *
 * @throws Error when the request fails so the caller can surface a toast.
 */
export async function downloadPublishedRecord(
  transmittalId: string,
  filename?: string,
): Promise<void> {
  const token = getAuthToken();
  const res = await fetch(
    `/api/v1/record-publishing/${encodeURIComponent(transmittalId)}/record.pdf`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!res.ok) {
    let message = `Download failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) message = String(body.detail);
    } catch {
      // Non-JSON error body — keep the status-code message.
    }
    throw new Error(message);
  }
  const blob = await res.blob();
  triggerDownload(blob, filename || `record-${transmittalId}.pdf`);
}
