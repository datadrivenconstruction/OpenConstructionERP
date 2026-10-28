// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// API client for the File Transmittals (W7) feature.
//
// Endpoints (mounted by the module loader at /api/v1/file-transmittals):
//   GET    /v1/file-transmittals/?project_id={uuid}
//   POST   /v1/file-transmittals/
//   GET    /v1/file-transmittals/{id}
//   POST   /v1/file-transmittals/{id}/send/
//   POST   /v1/file-transmittals/{id}/items/
//   DELETE /v1/file-transmittals/{id}/items/{iid}/
//   POST   /v1/file-transmittals/{id}/recipients/
//   POST   /v1/file-transmittals/ack/{token}/  (public)
//   GET    /v1/file-transmittals/{id}/cover/

import { apiDelete, apiGet, apiPost } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import type {
  Transmittal,
  TransmittalAcknowledgeResponse,
  TransmittalCreatePayload,
  TransmittalItem,
  TransmittalItemPayload,
  TransmittalListRow,
  TransmittalRecipient,
  TransmittalRecipientPayload,
} from './types';

const BASE = '/v1/file-transmittals';

export async function listTransmittals(
  projectId: string,
): Promise<TransmittalListRow[]> {
  const params = new URLSearchParams({ project_id: projectId });
  return apiGet<TransmittalListRow[]>(`${BASE}/?${params.toString()}`);
}

export async function getTransmittal(transmittalId: string): Promise<Transmittal> {
  return apiGet<Transmittal>(`${BASE}/${transmittalId}`);
}

export async function createTransmittal(
  payload: TransmittalCreatePayload,
): Promise<Transmittal> {
  return apiPost<Transmittal, TransmittalCreatePayload>(`${BASE}/`, payload);
}

export async function sendTransmittal(transmittalId: string): Promise<Transmittal> {
  return apiPost<Transmittal>(`${BASE}/${transmittalId}/send/`, {});
}

export async function addTransmittalItem(
  transmittalId: string,
  payload: TransmittalItemPayload,
): Promise<TransmittalItem> {
  return apiPost<TransmittalItem, TransmittalItemPayload>(
    `${BASE}/${transmittalId}/items/`,
    payload,
  );
}

export async function removeTransmittalItem(
  transmittalId: string,
  itemId: string,
): Promise<void> {
  await apiDelete(`${BASE}/${transmittalId}/items/${itemId}/`);
}

export async function addTransmittalRecipient(
  transmittalId: string,
  payload: TransmittalRecipientPayload,
): Promise<TransmittalRecipient> {
  return apiPost<TransmittalRecipient, TransmittalRecipientPayload>(
    `${BASE}/${transmittalId}/recipients/`,
    payload,
  );
}

/**
 * Public recipient acknowledgement — no auth required.
 *
 * Called from a recipient's "ack" link in the cover-sheet email.
 */
export async function acknowledgeTransmittal(
  token: string,
): Promise<TransmittalAcknowledgeResponse> {
  return apiPost<TransmittalAcknowledgeResponse>(`${BASE}/ack/${token}/`, {});
}

/**
 * Trigger a browser download of the cover-sheet bytes.
 *
 * Uses ``fetch`` with the auth header rather than going through ``apiGet``
 * so we keep the binary response intact.
 */
export async function downloadTransmittalCover(
  transmittalId: string,
  fallbackName = 'transmittal-cover',
): Promise<void> {
  const headers = new Headers({ Accept: 'application/pdf, text/plain' });
  const token = useAuthStore.getState().accessToken;
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const res = await fetch(`/api${BASE}/${transmittalId}/cover/`, {
    method: 'GET',
    headers,
  });
  if (!res.ok) {
    throw new Error(`Cover sheet download failed (${res.status})`);
  }
  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') ?? '';
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match?.[1] ?? `${fallbackName}.pdf`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.style.display = 'none';
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 500);
}
