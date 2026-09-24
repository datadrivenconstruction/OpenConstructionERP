// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * REST client for the assistant's proposed changes.
 *
 * Every call goes through the shared API client, so auth, the silent token
 * refresh, the demonstration's read-only refusal and error normalisation work
 * exactly as they do for the rest of the app. A refused request throws
 * `ApiError`; `actionErrors.ts` reads its code and field messages.
 *
 * Responses are normalised on the way in (`normalizeChatAction`), so a
 * component can rely on every array and flag being present.
 */
import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import {
  isChatAction,
  normalizeActionList,
  normalizeChatAction,
  type ChatAction,
  type ChatActionBatchError,
  type ChatActionBatchResponse,
  type ChatActionListFilters,
  type ChatActionListResponse,
} from './types';

const BASE = '/v1/erp_chat/actions/';

function actionPath(id: string, suffix = ''): string {
  return `${BASE}${encodeURIComponent(id)}/${suffix}`;
}

/**
 * Query string for a list request. Keys without a value are left out
 * entirely: `project_id=` or `status=null` would be a filter on "nothing".
 */
export function buildActionListQuery(filters: ChatActionListFilters): string {
  const params = new URLSearchParams();
  const status = Array.isArray(filters.status) ? filters.status.join(',') : (filters.status as string | undefined);
  const entries: [string, string | number | undefined][] = [
    ['project_id', filters.project_id],
    ['status', status],
    ['session_id', filters.session_id],
    ['batch_id', filters.batch_id],
    ['limit', filters.limit],
    ['offset', filters.offset],
  ];
  for (const [key, value] of entries) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

/** Proposals visible to the caller, newest first, with per-status counts. */
export async function listChatActions(filters: ChatActionListFilters = {}): Promise<ChatActionListResponse> {
  const raw = await apiGet<unknown>(`${BASE}${buildActionListQuery(filters)}`);
  return normalizeActionList(raw);
}

/** One proposal as the server sees it now. */
export async function getChatAction(id: string): Promise<ChatAction> {
  return normalizeChatAction(await apiGet<ChatAction>(actionPath(id)));
}

/**
 * Change values of a proposal before it is applied. Send only the keys the
 * person changed; the server re-validates and rebuilds the preview.
 */
export async function patchChatAction(id: string, payload: Record<string, unknown>): Promise<ChatAction> {
  return normalizeChatAction(await apiPatch<ChatAction>(actionPath(id), { payload }));
}

/**
 * Write the change. Returns the action in status `applied`, or in status
 * `failed` (still HTTP 200) when the domain write itself failed.
 */
export async function applyChatAction(id: string): Promise<ChatAction> {
  return normalizeChatAction(await apiPost<ChatAction>(actionPath(id, 'apply/')));
}

/** Decline a proposal. Nothing is written to the project. */
export async function rejectChatAction(id: string, note?: string): Promise<ChatAction> {
  const body = note && note.trim() ? { note: note.trim() } : {};
  return normalizeChatAction(await apiPost<ChatAction>(actionPath(id, 'reject/'), body));
}

/**
 * Apply several proposals; each one succeeds or fails on its own. `items` holds
 * every visible action in its new state, `errors` the ids that were refused
 * (a locked bill, a changed record) with the reason.
 */
export async function applyChatActionsBatch(ids: string[]): Promise<ChatActionBatchResponse> {
  const raw = await apiPost<{ items?: unknown[]; errors?: unknown[] }>(`${BASE}apply-batch/`, { ids });
  const items = Array.isArray(raw?.items)
    ? raw.items.filter(isChatAction).map((a) => normalizeChatAction(a))
    : [];
  const errors: ChatActionBatchError[] = [];
  for (const e of Array.isArray(raw?.errors) ? raw.errors : []) {
    if (typeof e !== 'object' || e === null) continue;
    const r = e as Record<string, unknown>;
    if (typeof r.id !== 'string') continue;
    errors.push({
      id: r.id,
      status_code: typeof r.status_code === 'number' ? r.status_code : 400,
      code: typeof r.code === 'string' ? r.code : 'domain_error',
      message: typeof r.message === 'string' ? r.message : '',
      message_key: typeof r.message_key === 'string' ? r.message_key : null,
    });
  }
  return { items, errors };
}

/** Undo an applied change, when the record is unchanged since. */
export async function revertChatAction(id: string, note?: string): Promise<ChatAction> {
  const body = note && note.trim() ? { note: note.trim() } : {};
  return normalizeChatAction(await apiPost<ChatAction>(actionPath(id, 'revert/'), body));
}
