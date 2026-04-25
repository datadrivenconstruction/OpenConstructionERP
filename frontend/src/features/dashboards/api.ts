/**
 * API helpers for the Dashboards module (T01: snapshots).
 *
 * Backend endpoints (mounted at /api/v1/dashboards by the module loader):
 *   POST   /v1/dashboards/projects/{project_id}/snapshots   — multipart upload
 *   GET    /v1/dashboards/projects/{project_id}/snapshots   — list
 *   GET    /v1/dashboards/snapshots/{snapshot_id}            — detail
 *   DELETE /v1/dashboards/snapshots/{snapshot_id}            — remove
 *   GET    /v1/dashboards/snapshots/{snapshot_id}/manifest   — manifest.json
 */

import { apiGet, apiDelete } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types ──────────────────────────────────────────────────────────────── */

export interface SnapshotSourceFile {
  id: string;
  original_name: string;
  format: string;
  discipline: string | null;
  entity_count: number;
  bytes_size: number;
  converter_notes: Record<string, unknown>;
}

export interface SnapshotSummary {
  id: string;
  project_id: string;
  label: string;
  total_entities: number;
  total_categories: number;
  summary_stats: Record<string, number>;
  created_by_user_id: string;
  created_at: string;
}

export interface Snapshot extends SnapshotSummary {
  parquet_dir: string;
  parent_snapshot_id: string | null;
  source_files: SnapshotSourceFile[];
}

export interface SnapshotListResponse {
  total: number;
  items: SnapshotSummary[];
}

export interface SnapshotManifest {
  label: string;
  total_entities: number;
  total_categories: number;
  summary_stats: Record<string, number>;
  source_files: Array<Record<string, unknown>>;
  created_by_user_id: string;
  created_at: string;
}

export interface SnapshotError {
  message_key: string;
  message: string;
  details?: Record<string, unknown>;
}

/* ── Queries ────────────────────────────────────────────────────────────── */

export async function listSnapshots(
  projectId: string,
  opts?: { limit?: number; offset?: number },
): Promise<SnapshotListResponse> {
  const params = new URLSearchParams({
    limit: String(opts?.limit ?? 100),
    offset: String(opts?.offset ?? 0),
  });
  return apiGet<SnapshotListResponse>(
    `/v1/dashboards/projects/${encodeURIComponent(projectId)}/snapshots?${params.toString()}`,
  );
}

export async function getSnapshot(snapshotId: string): Promise<Snapshot> {
  return apiGet<Snapshot>(
    `/v1/dashboards/snapshots/${encodeURIComponent(snapshotId)}`,
  );
}

export async function getSnapshotManifest(
  snapshotId: string,
): Promise<SnapshotManifest> {
  return apiGet<SnapshotManifest>(
    `/v1/dashboards/snapshots/${encodeURIComponent(snapshotId)}/manifest`,
  );
}

/* ── Mutations ──────────────────────────────────────────────────────────── */

export interface CreateSnapshotInput {
  projectId: string;
  label: string;
  files: File[];
  disciplines?: Array<string | null>;
  parentSnapshotId?: string | null;
}

/**
 * Create a snapshot from uploaded CAD/BIM files.
 *
 * Uses a raw fetch (not apiPost) because the backend expects a multipart
 * body — apiPost serialises JSON. 413/422/409 responses come back as
 * a SnapshotError envelope; we re-throw with the structured message so
 * callers can key on `message_key`.
 */
export async function createSnapshot(input: CreateSnapshotInput): Promise<Snapshot> {
  const formData = new FormData();
  formData.append('label', input.label);
  for (const file of input.files) {
    formData.append('files', file, file.name);
  }
  if (input.disciplines) {
    for (const disc of input.disciplines) {
      formData.append('disciplines', disc ?? '');
    }
  }
  if (input.parentSnapshotId) {
    formData.append('parent_snapshot_id', input.parentSnapshotId);
  }

  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-DDC-Client': 'OE/1.0',
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(
    `/api/v1/dashboards/projects/${encodeURIComponent(input.projectId)}/snapshots?locale=en`,
    { method: 'POST', headers, body: formData },
  );

  if (!resp.ok) {
    let err: SnapshotError = {
      message_key: 'snapshot.unknown',
      message: `Snapshot upload failed (HTTP ${resp.status})`,
    };
    try {
      const body = await resp.json();
      if (typeof body?.message_key === 'string') {
        err = body as SnapshotError;
      } else if (typeof body?.detail === 'string') {
        err.message = body.detail;
      }
    } catch {
      // fall through with default
    }
    const thrown = new Error(err.message) as Error & { snapshotError: SnapshotError };
    thrown.snapshotError = err;
    throw thrown;
  }

  return resp.json();
}

export async function deleteSnapshot(snapshotId: string): Promise<void> {
  await apiDelete(`/v1/dashboards/snapshots/${encodeURIComponent(snapshotId)}`);
}
