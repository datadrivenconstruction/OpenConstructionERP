import { apiGet, apiPost } from '@/shared/lib/api';

const PREFIX = '/v1/acap';

export interface InteriorRenderResponse {
  interior_id: string;
  room_name: string;
  style: string;
  status: 'completed' | 'failed' | 'pending' | string;
  prompt: string;
  storage_key: string | null;
  source_url: string | null;
  error_message: string | null;
}

export function generateInterior(
  projectId: string,
  body: { room_name: string; style: string },
): Promise<InteriorRenderResponse> {
  return apiPost<InteriorRenderResponse>(
    `${PREFIX}/projects/${projectId}/interior:generate`,
    body,
    { longRunning: true },
  );
}

export function listInteriors(
  projectId: string,
  roomName?: string,
): Promise<InteriorRenderResponse[]> {
  const params = roomName ? `?room_name=${encodeURIComponent(roomName)}` : '';
  return apiGet<InteriorRenderResponse[]>(`${PREFIX}/projects/${projectId}/interiors${params}`);
}

export { isNotConfiguredError } from '@/acap/renderApi';
