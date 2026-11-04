// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * "Download for offline": one request pulls the open punch items, the day's
 * checklists and the crew for the session project into the reference cache.
 * Reads only; nothing here writes to the server.
 */

import { putRef, getRef, type RefRead } from '@/shared/lib/offline/refCache';
import { authHeaders, type FieldSession } from './fieldApi';

export interface OfflinePack {
  project_id: string;
  server_time: string;
  punch_items: PackPunchItem[];
  inspections: PackInspection[];
  roster: unknown[];
  punch_truncated: boolean;
  inspections_truncated: boolean;
}

export interface PackPunchItem {
  id: string;
  title: string;
  description?: string | null;
  priority: string;
  status: string;
  trade?: string | null;
}

export interface PackInspection {
  id: string;
  title: string;
  inspection_type: string;
  location?: string | null;
  status: string;
  checklist_data: Array<Record<string, unknown>>;
}

/** Items stored by a download: what the person is told, "N items saved". */
export function packItemCount(pack: Pick<OfflinePack, 'punch_items' | 'inspections'>): number {
  return pack.punch_items.length + pack.inspections.length;
}

/**
 * Fetch the pack and store its parts. Returns the item count, or null when the
 * request did not land (no signal, expired session): the caller shows a retry.
 */
export async function downloadForOffline(
  session: FieldSession,
  fetchImpl: typeof fetch = fetch,
): Promise<number | null> {
  try {
    const res = await fetchImpl('/api/v1/field-diary/offline-pack/', {
      headers: authHeaders(session),
    });
    if (!res.ok) return null;
    const pack = (await res.json()) as OfflinePack;
    const now = Date.now();
    await putRef(session.projectId, 'punch_items', pack.punch_items, pack.server_time, now);
    await putRef(session.projectId, 'inspections', pack.inspections, pack.server_time, now);
    await putRef(session.projectId, 'roster', pack.roster, pack.server_time, now);
    return packItemCount(pack);
  } catch {
    return null;
  }
}

/** What is stored for this project, for a "downloaded N days ago" line. */
export async function readStoredPunch(projectId: string): Promise<RefRead<PackPunchItem[]> | null> {
  return getRef<PackPunchItem[]>(projectId, 'punch_items');
}
