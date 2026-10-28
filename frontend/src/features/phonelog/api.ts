// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// API client for phone-log capture. The create path posts a raw, free-form
// capture; the server normalizes it (parties, direction, channel, duration,
// summary, extracted instructions) and returns the canonical record.

import { apiDelete, apiGet, apiPatch, apiPost, getAuthToken } from '@/shared/lib/api';
import type { PhoneLog, PhoneLogCreate, PhoneLogFinalize } from './types';

const BASE = '/v1/phonelog';

export function listPhoneLogs(
  projectId: string,
  opts?: { direction?: string; channel?: string; limit?: number; offset?: number },
): Promise<PhoneLog[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (opts?.direction) params.set('direction', opts.direction);
  if (opts?.channel) params.set('channel', opts.channel);
  // The backend caps limit at 100; pass it so a fuller history is fetched for
  // client-side search, filtering, and pagination.
  if (opts?.limit != null) params.set('limit', String(opts.limit));
  if (opts?.offset != null) params.set('offset', String(opts.offset));
  return apiGet<PhoneLog[]>(`${BASE}/?${params.toString()}`);
}

export function createPhoneLog(body: PhoneLogCreate): Promise<PhoneLog> {
  return apiPost<PhoneLog, PhoneLogCreate>(`${BASE}/`, body);
}

// Upload a recording (audio or video) and get back a DRAFT protocol for review.
// Uses a raw multipart fetch: apiPost forces a JSON content-type, which would
// break the multipart boundary. Query params carry the project + optional hints.
export async function transcribeRecording(
  projectId: string,
  file: File,
  opts?: { occurredAt?: string | null; direction?: string | null },
): Promise<PhoneLog> {
  const params = new URLSearchParams({ project_id: projectId });
  if (opts?.occurredAt) params.set('occurred_at', opts.occurredAt);
  if (opts?.direction) params.set('direction', opts.direction);

  const form = new FormData();
  form.append('file', file);

  const token = getAuthToken();
  const res = await fetch(`/api${BASE}/transcribe?${params.toString()}`, {
    method: 'POST',
    headers: { 'X-DDC-Client': 'OE/1.0', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: form,
  });
  if (!res.ok) {
    let detail = `Upload failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // response was not JSON; keep the generic message
    }
    throw new Error(detail);
  }
  return (await res.json()) as PhoneLog;
}

// Confirm a reviewed draft into a normal, logged phone-log record.
export function finalizePhoneLog(id: string, body: PhoneLogFinalize): Promise<PhoneLog> {
  return apiPatch<PhoneLog, PhoneLogFinalize>(`${BASE}/${id}`, body);
}

// Discard a draft (or delete a record) together with its stored recording.
export function deletePhoneLog(id: string): Promise<void> {
  return apiDelete<void>(`${BASE}/${id}`);
}

// Fetch the stored recording as a blob for in-browser playback. A raw fetch is
// used so the auth header is attached and an object URL can be built from it.
export async function fetchRecordingBlob(id: string): Promise<Blob> {
  const token = getAuthToken();
  const res = await fetch(`/api${BASE}/${id}/audio`, {
    headers: { 'X-DDC-Client': 'OE/1.0', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!res.ok) throw new Error(`Could not load the recording (${res.status})`);
  return res.blob();
}
