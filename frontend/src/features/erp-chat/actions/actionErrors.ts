// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Turning a refused or failed change into a sentence a site manager can act on.
 *
 * Two kinds of failure reach a proposal card:
 *
 * 1. The request was refused (HTTP 4xx). Nothing was written. The server sends
 *    a structured detail (erp_chat/actions/base.py `ActionError.to_detail`):
 *      `{"detail": {"code": "locked", "message": "...", "message_key":
 *        "erp_chat.action.error.locked", "params": {...},
 *        "field_errors": {"<key>": {"code", "message_key", "message"}}}}`
 *    The sentence shown is the server's own key, translated, with its English
 *    message as the fallback. Older or foreign shapes are still read:
 *      `{"detail": {"error_code" | "error": "locked"}}`, `{"code": "locked"}`,
 *      FastAPI's `{"detail": [{"loc": ["body", "payload", "<key>"], "msg"}]}`,
 *      `{"detail": {"fields": {"<key>": "message"}}}`,
 *      `{"detail": {"errors": [{"field": "<key>", "message": "..."}]}}`.
 *    Without a server key, a known code gets this module's own sentence, then
 *    the HTTP status decides.
 *
 * 2. The domain write itself failed. The server answers 200 with the action in
 *    status `failed` and `error` / `error_code` set; `describeFailure` maps it.
 *
 * The fallback sentences live under `erp_chat.action.request_error.*` so they
 * never collide with the server-owned `erp_chat.action.error.*` keys.
 */
import type { TFunction } from 'i18next';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import type { ActionOp, ChatAction } from './types';

/** Prefix of the server-owned error keys (labels.ERROR_PREFIX in the backend). */
const SERVER_ERROR_PREFIX = 'erp_chat.action.error.';

/** A message with the key that translates it, when the server named one. */
export interface KeyedMessage {
  message: string;
  key: string | null;
}

/** What the store keeps about a refused request; the sentence is built at render. */
export interface ActionRequestError {
  op: ActionOp;
  status: number | null;
  code: string | null;
  /** The server's i18n key for the sentence, and its placeholder values. */
  messageKey: string | null;
  params: Record<string, unknown>;
  /** Payload key -> message, for inline errors on the edit form. */
  fieldErrors: Record<string, KeyedMessage>;
  /** The server's own (or the network layer's) English message. */
  serverMessage: string | null;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function firstString(...values: unknown[]): string | null {
  for (const v of values) if (typeof v === 'string' && v.length > 0) return v;
  return null;
}

/** The machine code of a refused request, or null. */
export function readErrorCode(body: unknown): string | null {
  if (!isRecord(body)) return null;
  const detail = body.detail;
  if (isRecord(detail)) {
    const code = firstString(detail.code, detail.error_code, detail.error);
    if (code) return code;
  }
  return firstString(body.code, body.error_code);
}

function readMessageKey(body: unknown): { key: string | null; params: Record<string, unknown> } {
  if (!isRecord(body) || !isRecord(body.detail)) return { key: null, params: {} };
  const d = body.detail;
  return { key: firstString(d.message_key), params: isRecord(d.params) ? d.params : {} };
}

/** Field-level messages of a refused edit, keyed by payload key. */
export function readFieldErrors(body: unknown): Record<string, KeyedMessage> {
  const out: Record<string, KeyedMessage> = {};
  if (!isRecord(body)) return out;
  const detail = body.detail;
  if (Array.isArray(detail)) {
    for (const entry of detail) {
      if (!isRecord(entry) || typeof entry.msg !== 'string') continue;
      const loc = Array.isArray(entry.loc) ? entry.loc.filter((p): p is string => typeof p === 'string') : [];
      const key = loc.filter((p) => p !== 'body' && p !== 'payload').pop();
      if (key && !out[key]) out[key] = { message: entry.msg, key: null };
    }
    return out;
  }
  if (!isRecord(detail)) return out;
  for (const mapName of ['field_errors', 'fields'] as const) {
    const map = detail[mapName];
    if (!isRecord(map)) continue;
    for (const [k, v] of Object.entries(map)) {
      if (out[k]) continue;
      if (isRecord(v)) {
        const message = firstString(v.message, v.msg);
        if (message) out[k] = { message, key: firstString(v.message_key) };
      } else {
        const message = Array.isArray(v) ? firstString(...v) : firstString(v);
        if (message) out[k] = { message, key: null };
      }
    }
  }
  if (Array.isArray(detail.errors)) {
    for (const e of detail.errors) {
      if (!isRecord(e)) continue;
      const k = firstString(e.field, e.key);
      const message = firstString(e.message, e.msg);
      if (k && message && !out[k]) out[k] = { message, key: firstString(e.message_key) };
    }
  }
  return out;
}

/** Everything the UI needs to know about a refused request. */
export function toActionRequestError(err: unknown, op: ActionOp): ActionRequestError {
  if (err instanceof ApiError) {
    const { key, params } = readMessageKey(err.body);
    return {
      op,
      status: err.status,
      code: readErrorCode(err.body),
      messageKey: key,
      params,
      fieldErrors: readFieldErrors(err.body),
      serverMessage: err.message || null,
    };
  }
  return {
    op,
    status: null,
    code: null,
    messageKey: null,
    params: {},
    fieldErrors: {},
    serverMessage: getErrorMessage(err),
  };
}

/** A field message in the reader's language. */
export function fieldErrorText(e: KeyedMessage, t: TFunction): string {
  return e.key ? String(t(e.key, { defaultValue: e.message })) : e.message;
}

/**
 * This build's own sentence for a known code, used only when the server did
 * not name a key. Returns null for a code this build does not know.
 */
export function messageForCode(code: string | null, t: TFunction): string | null {
  switch (code) {
    case 'locked':
      return String(
        t('erp_chat.action.request_error.locked', {
          defaultValue:
            'This bill of quantities is locked, so nothing was changed. Create a revision of the bill to make changes.',
        }),
      );
    case 'target_changed':
      return String(
        t('erp_chat.action.request_error.target_changed', {
          defaultValue:
            'Someone changed this record after the assistant prepared the change, so nothing was applied. Reject it and ask again so the assistant works from the current values.',
        }),
      );
    case 'changed_since_apply':
      return String(
        t('erp_chat.action.request_error.changed_since_apply', {
          defaultValue:
            'This record was edited after the change was applied. Undoing it now would overwrite newer work, so open the record and adjust it by hand.',
        }),
      );
    case 'not_pending':
    case 'not_proposed':
    case 'already_decided':
      return String(
        t('erp_chat.action.request_error.already_decided', {
          defaultValue: 'This change was already handled, maybe in another window. Its current state is shown now.',
        }),
      );
    case 'forbidden':
    case 'permission_denied':
      return String(
        t('erp_chat.action.request_error.forbidden', {
          defaultValue: 'You do not have permission to make this change in this project.',
        }),
      );
    default:
      return null;
  }
}

/** The sentence shown for a refused request. */
export function describeRequestError(e: ActionRequestError, t: TFunction): string {
  // The public demonstration refuses every write with its own, already
  // translated sentence (see `ApiError`); that sentence is the right one here.
  if (e.code === 'demo_read_only' && e.serverMessage) return e.serverMessage;
  if (e.messageKey) {
    const fallback = e.serverMessage ?? messageForCode(e.code, t) ?? '';
    return String(t(e.messageKey, { ...e.params, defaultValue: fallback }));
  }
  const known = messageForCode(e.code, t);
  if (known) return known;
  if (e.status === 403) {
    return String(
      t('erp_chat.action.request_error.forbidden', {
        defaultValue: 'You do not have permission to make this change in this project.',
      }),
    );
  }
  if (e.status === 404) {
    return String(
      t('erp_chat.action.request_error.not_found', {
        defaultValue: 'This change is no longer available to you.',
      }),
    );
  }
  if (e.status === 409) {
    return String(
      t('erp_chat.action.request_error.already_decided', {
        defaultValue: 'This change was already handled, maybe in another window. Its current state is shown now.',
      }),
    );
  }
  if (e.status === 422 && Object.keys(e.fieldErrors).length > 0) {
    return String(
      t('erp_chat.action.request_error.fields', {
        defaultValue: 'Some values need attention before this can be saved.',
      }),
    );
  }
  return (
    e.serverMessage ??
    String(t('erp_chat.action.request_error.generic', { defaultValue: 'Something went wrong. Nothing was changed.' }))
  );
}

/**
 * Codes whose server sentence is generic ("The change could not be saved.").
 * For these the stored `error` text says more, so it is shown as it is.
 */
const GENERIC_FAILURE_CODES = new Set(['domain_error', 'internal_error']);

/** The sentence shown on a card whose domain write failed. */
export function describeFailure(action: ChatAction, t: TFunction): string {
  const generic = String(
    t('erp_chat.action.request_error.apply_failed', {
      defaultValue: 'The change could not be written. Nothing was changed.',
    }),
  );
  const code = action.error_code;
  if (code && !GENERIC_FAILURE_CODES.has(code)) {
    return String(t(`${SERVER_ERROR_PREFIX}${code}`, { defaultValue: action.error ?? messageForCode(code, t) ?? generic }));
  }
  return action.error ?? generic;
}
