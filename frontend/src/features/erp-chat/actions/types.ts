// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wire types for the AI assistant's proposed changes (`/v1/erp_chat/actions/`).
 *
 * A proposal is a row the assistant prepared and nobody has applied yet. It
 * only reaches the domain tables when a person clicks Apply, which is why the
 * DTO carries both what the model proposed (`original_payload`) and what is
 * about to be written (`payload`), plus who decided and when.
 *
 * Field names mirror the backend `ChatActionResponse` exactly (snake_case).
 * `normalizeChatAction` fills the optional parts so a component never has to
 * guard every property: a missing `fields` array renders as "no details", not
 * as a crash in the middle of a conversation.
 */

/** Lifecycle of a proposal on the server. */
export type ActionStatus = 'proposed' | 'applied' | 'rejected' | 'failed' | 'reverted';

export const ACTION_STATUSES: readonly ActionStatus[] = [
  'proposed',
  'applied',
  'rejected',
  'failed',
  'reverted',
] as const;

/**
 * How a field's value is shown and edited.
 *
 * - `number`: plain number, optional `unit` token (`m3`, `pcs`, ...).
 * - `money`: amount with an ISO 4217 `currency`; the value may arrive as a
 *   Decimal string and keeps that wire type when edited.
 * - `percent`: percentage POINTS on a 0-100 scale (42.5 means 42.5 %), the
 *   scale schedule progress uses. It is never a 0-1 ratio.
 * - `date`: `YYYY-MM-DD` (a full ISO timestamp is accepted and read as its day).
 * - `enum`: one of `options[].value`.
 * - `ref`: a reference to another record, read-only here. Either a plain
 *   label string or `{id, label, url}`.
 */
export type ActionFieldKind =
  | 'text'
  | 'longtext'
  | 'number'
  | 'money'
  | 'date'
  | 'enum'
  | 'percent'
  | 'ref';

export interface ActionFieldOption {
  value: string;
  label_key?: string | null;
  label?: string | null;
}

export interface ActionField {
  /** Payload key the field maps to; an edit sends `{[key]: newValue}`. */
  key: string;
  /** i18n key `erp_chat.action.field.<key>`; `label` is its English fallback. */
  label_key?: string | null;
  label: string;
  kind: ActionFieldKind;
  value: unknown;
  /** Value of the existing record before the change (edits only, else null). */
  before?: unknown;
  currency?: string | null;
  unit?: string | null;
  options?: ActionFieldOption[] | null;
  editable: boolean;
  required: boolean;
}

/** A record the action points at (`target`) or produced (`result`). */
export interface ActionEntityRef {
  entity_type: string;
  entity_id: string;
  label?: string | null;
  url?: string | null;
}

export interface ActionUserRef {
  id: string;
  name: string | null;
}

/**
 * Something the person should know before applying ("No project member
 * matches Paul, so the task will be created without an assignee"). `text` is
 * the English rendering with `params` filled in; `field` names the field the
 * note is about, when there is one.
 */
export interface ActionNote {
  key: string;
  text: string;
  params: Record<string, unknown>;
  field: string | null;
  tone: 'info' | 'warning';
}

export interface ChatAction {
  id: string;
  session_id: string | null;
  message_id: string | null;
  project_id: string | null;
  project_name: string | null;
  /** Dotted type such as `boq.add_position` or `task.create`. */
  action_type: string;
  status: ActionStatus;
  /** English fallback of `title_key` (`erp_chat.action.type.<action_type>`). */
  title: string;
  title_key: string | null;
  summary: string | null;
  /** Data text such as the BOQ name or the task title. Never translated. */
  subtitle: string | null;
  fields: ActionField[];
  notes: ActionNote[];
  payload: Record<string, unknown>;
  original_payload: Record<string, unknown>;
  /** True when a person changed the proposal before it was applied. */
  edited: boolean;
  /** 0..1, or null when the model gave none. */
  confidence: number | null;
  rationale: string | null;
  target: ActionEntityRef | null;
  result: ActionEntityRef | null;
  requested_by: ActionUserRef | null;
  decided_by: ActionUserRef | null;
  decided_at: string | null;
  reverted_by: ActionUserRef | null;
  reverted_at: string | null;
  decision_note: string | null;
  revert_note: string | null;
  error: string | null;
  error_code: string | null;
  /** Computed for the CALLER: what this person may do right now. */
  can_apply: boolean;
  can_edit: boolean;
  can_reject: boolean;
  can_revert: boolean;
  /** Why a waiting action cannot be applied by the caller (i18n key + English text). */
  blocked_reason_key: string | null;
  blocked_reason: string | null;
  /** i18n key naming a side effect an undo cannot take back, or null. */
  revert_hint_key: string | null;
  /** English text of `revert_hint_key`. */
  revert_hint: string | null;
  batch_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatActionCounts {
  proposed: number;
  applied: number;
  rejected: number;
  failed: number;
  reverted: number;
}

export interface ChatActionListResponse {
  items: ChatAction[];
  /** Rows matching the filter, not `items.length`. */
  total: number;
  /** Per-status counts for the same scope, ignoring the status filter. */
  counts: ChatActionCounts;
}

export interface ChatActionListFilters {
  project_id?: string;
  /** One status, or several (sent as `status=proposed,failed`). */
  status?: ActionStatus | readonly ActionStatus[];
  session_id?: string;
  batch_id?: string;
  limit?: number;
  offset?: number;
}

/** Why one id of an apply-all was refused (the others are unaffected). */
export interface ChatActionBatchError {
  id: string;
  status_code: number;
  code: string;
  message: string;
  message_key: string | null;
}

export interface ChatActionBatchResponse {
  items: ChatAction[];
  errors: ChatActionBatchError[];
}

/** A request the person started on a proposal; drives the busy states. */
export type ActionOp = 'apply' | 'reject' | 'save' | 'revert';

/** Statuses after which nothing about the row can change any more. */
export function isTerminalStatus(status: ActionStatus): boolean {
  return status === 'rejected' || status === 'reverted';
}

const EMPTY_COUNTS: ChatActionCounts = { proposed: 0, applied: 0, rejected: 0, failed: 0, reverted: 0 };

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function str(v: unknown): string | null {
  return typeof v === 'string' && v.length > 0 ? v : null;
}

function userRef(v: unknown): ActionUserRef | null {
  if (!isRecord(v)) return null;
  const id = str(v.id) ?? (typeof v.id === 'number' ? String(v.id) : null);
  if (!id) return null;
  return { id, name: str(v.name) };
}

function entityRef(v: unknown): ActionEntityRef | null {
  if (!isRecord(v)) return null;
  const entityId = str(v.entity_id) ?? (typeof v.entity_id === 'number' ? String(v.entity_id) : null);
  if (!entityId && !str(v.url)) return null;
  return {
    entity_type: str(v.entity_type) ?? '',
    entity_id: entityId ?? '',
    label: str(v.label),
    url: str(v.url),
  };
}

const FIELD_KINDS: readonly ActionFieldKind[] = [
  'text',
  'longtext',
  'number',
  'money',
  'date',
  'enum',
  'percent',
  'ref',
];

function normalizeField(v: unknown): ActionField | null {
  if (!isRecord(v)) return null;
  const key = str(v.key);
  if (!key) return null;
  const kind = FIELD_KINDS.includes(v.kind as ActionFieldKind) ? (v.kind as ActionFieldKind) : 'text';
  const options = Array.isArray(v.options)
    ? v.options
        .filter(isRecord)
        .map((o) => ({
          value: String(o.value ?? ''),
          label_key: str(o.label_key),
          label: str(o.label),
        }))
    : null;
  return {
    key,
    label_key: str(v.label_key),
    label: str(v.label) ?? key,
    kind,
    value: v.value ?? null,
    before: v.before ?? null,
    currency: str(v.currency),
    unit: str(v.unit),
    options,
    editable: v.editable === true,
    required: v.required === true,
  };
}

function normalizeNote(v: unknown): ActionNote | null {
  if (!isRecord(v)) return null;
  const key = str(v.key);
  const text = str(v.text);
  if (!key && !text) return null;
  return {
    key: key ?? '',
    text: text ?? '',
    params: isRecord(v.params) ? v.params : {},
    field: str(v.field),
    tone: v.tone === 'warning' ? 'warning' : 'info',
  };
}

/**
 * True when `data` has the shape of a proposal DTO. Used by the chat renderer
 * and by the dock to pick proposals out of tool results.
 */
export function isChatAction(data: unknown): data is ChatAction {
  return (
    isRecord(data) &&
    typeof data.id === 'string' &&
    data.id.length > 0 &&
    typeof data.action_type === 'string' &&
    typeof data.status === 'string'
  );
}

/**
 * Fill every optional part of a DTO with a safe default. Unknown statuses are
 * kept as `proposed` only when the row can still be applied; otherwise they
 * read as `failed`, which never offers a write the server did not allow.
 */
export function normalizeChatAction(raw: ChatAction | Record<string, unknown>): ChatAction {
  const r = raw as Record<string, unknown>;
  const status = ACTION_STATUSES.includes(r.status as ActionStatus)
    ? (r.status as ActionStatus)
    : r.can_apply === true
      ? 'proposed'
      : 'failed';
  const payload = isRecord(r.payload) ? r.payload : {};
  const original = isRecord(r.original_payload) ? r.original_payload : payload;
  const confidence =
    typeof r.confidence === 'number' && Number.isFinite(r.confidence)
      ? Math.min(1, Math.max(0, r.confidence))
      : null;
  return {
    id: String(r.id),
    session_id: str(r.session_id),
    message_id: str(r.message_id),
    project_id: str(r.project_id),
    project_name: str(r.project_name),
    action_type: str(r.action_type) ?? 'unknown',
    status,
    title: str(r.title) ?? str(r.action_type) ?? '',
    title_key: str(r.title_key),
    summary: str(r.summary),
    subtitle: str(r.subtitle),
    fields: Array.isArray(r.fields)
      ? r.fields.map(normalizeField).filter((f): f is ActionField => f !== null)
      : [],
    notes: Array.isArray(r.notes)
      ? r.notes.map(normalizeNote).filter((n): n is ActionNote => n !== null)
      : [],
    payload,
    original_payload: original,
    edited: r.edited === true,
    confidence,
    rationale: str(r.rationale),
    target: entityRef(r.target),
    result: entityRef(r.result),
    requested_by: userRef(r.requested_by),
    decided_by: userRef(r.decided_by),
    decided_at: str(r.decided_at),
    reverted_by: userRef(r.reverted_by),
    reverted_at: str(r.reverted_at),
    decision_note: str(r.decision_note),
    revert_note: str(r.revert_note),
    error: str(r.error),
    error_code: str(r.error_code),
    can_apply: r.can_apply === true,
    can_edit: r.can_edit === true,
    can_reject: r.can_reject === true,
    can_revert: r.can_revert === true,
    blocked_reason_key: str(r.blocked_reason_key),
    blocked_reason: str(r.blocked_reason),
    revert_hint_key: str(r.revert_hint_key),
    revert_hint: str(r.revert_hint),
    batch_id: str(r.batch_id),
    created_at: str(r.created_at) ?? new Date(0).toISOString(),
    updated_at: str(r.updated_at) ?? str(r.created_at) ?? new Date(0).toISOString(),
  };
}

/** Normalise a list envelope; missing counts read as zero, never undefined. */
export function normalizeActionList(raw: unknown): ChatActionListResponse {
  const r = isRecord(raw) ? raw : {};
  const items = Array.isArray(r.items)
    ? r.items.filter(isChatAction).map((a) => normalizeChatAction(a))
    : [];
  const c = isRecord(r.counts) ? r.counts : {};
  const counts: ChatActionCounts = { ...EMPTY_COUNTS };
  for (const s of ACTION_STATUSES) {
    const n = c[s];
    counts[s] = typeof n === 'number' && Number.isFinite(n) ? n : 0;
  }
  const total = typeof r.total === 'number' && Number.isFinite(r.total) ? r.total : items.length;
  return { items, total, counts };
}

/** The first segment of `action_type` (`boq.add_position` -> `boq`). */
export function actionDomain(actionType: string): string {
  const dot = actionType.indexOf('.');
  return (dot > 0 ? actionType.slice(0, dot) : actionType).toLowerCase();
}
