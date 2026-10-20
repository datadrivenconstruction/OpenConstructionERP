// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Unified approvals/alerts inbox - API client + wire types.
 *
 * Mirrors the backend ``GET /api/v1/dashboard/inbox/`` payload
 * (``app/modules/dashboard/schemas.py::InboxResponse``). The endpoint
 * aggregates the caller's pending approvals (file-approval steps +
 * change-order approval steps) and their unread in-app notifications, scoped
 * IDOR-safely to accessible projects. We READ existing per-module data - this
 * client introduces no new store.
 */
import { ApiError, apiDelete, apiGet, apiPost } from '@/shared/lib/api';

export type InboxKind = 'approval' | 'alert';
export type InboxSeverity = 'info' | 'warning' | 'critical';
/** What the caller recorded against a row. ``null`` once it is restored. */
export type InboxState = 'acknowledged' | 'dismissed' | null;

/** One actionable row in the unified inbox. */
export interface InboxItem {
  /** Stable per-source id, e.g. ``notification:<uuid>``. */
  id: string;
  kind: InboxKind;
  /** Module of origin, e.g. ``file_approval`` / ``change_order`` / ``notification``. */
  source: string;
  /** Resolved English text OR an i18n key (see ``title_key``). */
  title: string | null;
  /** i18n key the frontend renders with ``body_context`` when present. */
  title_key?: string | null;
  /** i18n key for the secondary body line (alert notifications). */
  body_key?: string | null;
  body_context?: Record<string, unknown>;
  project_id?: string | null;
  project_name?: string | null;
  entity_type?: string | null;
  entity_id?: string | null;
  /** Relative app route the row links to. */
  action_url?: string | null;
  severity: InboxSeverity;
  /** ISO-8601; drives the newest-first sort. */
  created_at?: string | null;
  /**
   * True when the caller marked this row seen. Acknowledged rows stay in the
   * list so they can recede without disappearing; dismissed rows are not
   * returned at all.
   */
  acknowledged?: boolean;
}

export interface InboxResponse {
  items: InboxItem[];
  /** Scoped count across both streams (pre-cap). */
  total: number;
  /** Scoped pending-approval count. */
  approvals_count: number;
  /** Scoped alert count. */
  alerts_count: number;
  generated_at: string;
}

/**
 * Fetch the unified inbox for the signed-in user.
 *
 * @param limit Maximum rows in the returned list (1-200). Counts are pre-cap.
 */
export function fetchInbox(limit = 50): Promise<InboxResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  return apiGet<InboxResponse>(`/v1/dashboard/inbox/?${params.toString()}`);
}

/** One validation finding the server recorded alongside an action. */
export interface InboxActionFinding {
  rule_id: string;
  severity: string;
  message: string;
  suggestion?: string | null;
}

/** Outcome of acknowledging, dismissing or restoring one row. */
export interface InboxActionResponse {
  item_id: string;
  state: InboxState;
  /**
   * Non-blocking findings. Dismissing an approval reports here that the step is
   * still pending a decision - the frontend renders its own translated note off
   * the row's kind rather than showing this English text.
   */
  findings: InboxActionFinding[];
}

const ITEM_BASE = (itemId: string) => `/v1/dashboard/inbox/${encodeURIComponent(itemId)}`;

/**
 * A row that is already off the caller's list answers 404 to a second dismiss,
 * acknowledge or undo (double click, another tab, an alert read elsewhere). The
 * wanted end state holds, so that is success, not an error toast.
 */
async function idempotent(
  itemId: string,
  state: InboxState,
  call: () => Promise<InboxActionResponse>,
): Promise<InboxActionResponse> {
  try {
    return await call();
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return { item_id: itemId, state, findings: [] };
    }
    throw error;
  }
}

/** Mark a row seen. It stays in the list, flagged, and nothing else changes. */
export function acknowledgeInboxItem(itemId: string): Promise<InboxActionResponse> {
  return idempotent(itemId, 'acknowledged', () =>
    apiPost<InboxActionResponse>(`${ITEM_BASE(itemId)}/acknowledge`, {}));
}

/**
 * Take a row off the caller's list. An alert is also marked read so the
 * notifications screen agrees; an approval stays pending in the module that
 * owns it, which is triage, not a decision.
 */
export function dismissInboxItem(itemId: string): Promise<InboxActionResponse> {
  return idempotent(itemId, 'dismissed', () =>
    apiPost<InboxActionResponse>(`${ITEM_BASE(itemId)}/dismiss`, {}));
}

/** Undo an acknowledge or a dismiss and put the row back on the list. */
export function restoreInboxItem(itemId: string): Promise<InboxActionResponse> {
  return idempotent(itemId, null, () =>
    apiDelete<InboxActionResponse>(`${ITEM_BASE(itemId)}/state`));
}
