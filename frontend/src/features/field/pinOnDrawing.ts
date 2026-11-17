// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Pin on drawing" for the field shell: the sheet list and sheet pictures are cached on the phone
 * (at most MAX_CACHED_SHEETS pictures) so a defect can be pinned with no signal, and the pin rides
 * the same offline queue as the defect it belongs to.
 */

import type { EnqueueInput } from '@/shared/lib/offline';
import { authHeaders, type FieldSession } from './fieldApi';

export const MAX_CACHED_SHEETS = 30;
export const PLAN_PIN_KIND = 'field.plan_pin';
const CACHE_NAME = 'oe-field-sheets';
const LIST_KEY = 'oe-field-sheet-list';

export interface FieldSheet {
  document_id: string;
  name: string;
  revision_code?: string | null;
  pages: number;
}

export interface PinPlacement {
  documentId: string;
  page: number;
  x: number;
  y: number;
}

export function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v));
}

/** The queue op that pins a record raised earlier in the same queue (`recordClientOpId`). */
export function buildPlanPinOp(
  clientOpId: string,
  recordKind: 'punch' | 'ncr' | 'inspection',
  recordClientOpId: string,
  at: PinPlacement,
): EnqueueInput {
  return {
    clientOpId,
    method: 'POST',
    path: '/v1/field-diary/capture/plan-pin/',
    kind: PLAN_PIN_KIND,
    body: {
      record_kind: recordKind,
      record_client_op_id: recordClientOpId,
      document_id: at.documentId,
      page: at.page,
      x: clamp01(at.x),
      y: clamp01(at.y),
    },
  };
}

function listKey(projectId: string): string {
  return `${LIST_KEY}:${projectId}`;
}

/** Fresh list when online, the last stored one otherwise. */
export async function loadSheets(session: FieldSession, fetchImpl: typeof fetch = fetch): Promise<FieldSheet[]> {
  try {
    const res = await fetchImpl('/api/v1/field-diary/sheets/?limit=100', { headers: authHeaders(session) });
    if (res.ok) {
      const body = (await res.json()) as { items: FieldSheet[] };
      try {
        localStorage.setItem(listKey(session.projectId), JSON.stringify(body.items));
      } catch {
        /* storage full or blocked: the list still shows this time */
      }
      return body.items;
    }
  } catch {
    /* offline: fall through to the stored list */
  }
  try {
    return JSON.parse(localStorage.getItem(listKey(session.projectId)) ?? '[]') as FieldSheet[];
  } catch {
    return [];
  }
}

export function sheetImageUrl(documentId: string, page: number): string {
  return `/api/v1/field-diary/sheets/${documentId}/pages/${page}/image/`;
}

/** Keep the newest `cap` entries: older pictures are dropped first. */
export function overflowKeys(keys: readonly string[], cap: number = MAX_CACHED_SHEETS): string[] {
  return keys.length > cap ? keys.slice(0, keys.length - cap) : [];
}

/** Picture of one sheet page as an object URL; downloaded once and then kept for offline use. */
export async function sheetPicture(session: FieldSession, documentId: string, page: number): Promise<string | null> {
  const url = sheetImageUrl(documentId, page);
  try {
    const cache = await caches.open(CACHE_NAME);
    let res = await cache.match(url);
    if (!res) {
      const net = await fetch(url, { headers: authHeaders(session) });
      if (!net.ok) return null;
      await cache.put(url, net.clone());
      const stale = overflowKeys((await cache.keys()).map((r) => r.url));
      for (const k of stale) await cache.delete(k);
      res = net;
    }
    return URL.createObjectURL(await res.blob());
  } catch {
    return null;
  }
}
