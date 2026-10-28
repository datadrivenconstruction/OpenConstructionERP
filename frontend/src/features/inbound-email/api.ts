// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helper for the Inbound Email module.
 *
 * Backed by /api/v1/inbound-email/ — see
 * backend/app/modules/inbound_email/router.py
 *
 * One call, and it takes a file rather than JSON. The shared `apiPost` sets
 * `Content-Type: application/json` on any body it is given, which would strip
 * the multipart boundary the browser needs to write, so the request is issued
 * here with the same Bearer token the shared client uses.
 *
 * Nothing is persisted by this endpoint: the response is the whole result, and
 * closing the page discards it.
 */

import { API_BASE, extractErrorMessageFromBody, getAuthToken } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface EmailAttachment {
  filename: string;
  content_type: string;
  size_bytes: number;
}

export interface ParsedEmail {
  message_id: string | null;
  subject: string;
  from_addr: string;
  to_addrs: string[];
  cc_addrs: string[];
  date_iso: string | null;
  in_reply_to: string | null;
  references: string[];
  body_text: string;
  attachments: EmailAttachment[];
}

/**
 * Kept equal to the CATEGORY_* tokens in the module's delay_detection.py.
 * They are stable strings on purpose, so a label can be translated without
 * the detector caring what it is called on screen.
 */
export type DelayCategory =
  | 'weather'
  | 'site_access'
  | 'late_information'
  | 'design_change'
  | 'variation'
  | 'resource_shortage'
  | 'statutory_approval'
  | 'unforeseen_ground';

export interface DelaySignal {
  category: DelayCategory | string;
  confidence: number;
  matched_phrases: string[];
  /** The category's fixed starter fragnet, in the backend's English. */
  suggested_activities: string[];
}

export interface InboundEmailAnalysis {
  email: ParsedEmail;
  delay_signals: DelaySignal[];
}

/* ── Calls ─────────────────────────────────────────────────────────────── */

/** Parse a stored RFC-822 message and return it with any delay signals in it. */
export async function analyzeInboundEmail(file: File): Promise<InboundEmailAnalysis> {
  const form = new FormData();
  form.append('file', file);

  const headers: Record<string, string> = {};
  const token = getAuthToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(`${API_BASE}/v1/inbound-email/parse`, {
    method: 'POST',
    headers,
    body: form,
  });

  if (!resp.ok) {
    let detail: string | null = null;
    try {
      detail = extractErrorMessageFromBody(await resp.json());
    } catch {
      // A non-JSON error body tells us nothing the status has not already.
    }
    throw new Error(detail ?? `Could not read the message (HTTP ${resp.status})`);
  }

  return (await resp.json()) as InboundEmailAnalysis;
}
