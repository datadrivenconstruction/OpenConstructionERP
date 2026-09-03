// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/** API client for the register workspace (`/api/v1/register-workflow/`). */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

export type Kind = 'rfi' | 'rfq' | 'order' | 'variation' | 'delay' | 'toolbox';

/**
 * Where an item stands. `withdrawn` is the third state the remove rail
 * added: something raised in error that has ALREADY been seen outside the
 * building cannot be deleted, so it is withdrawn instead - struck off the
 * open lists and out of tracking, but kept on the record with the reason
 * it was pulled. Only a never-emailed item can actually be deleted.
 */
export type RegisterStatus = 'open' | 'closed' | 'withdrawn';

export interface FieldSpec {
  label: string;
  type: 'text' | 'area' | 'date' | 'money' | 'select';
  is_due: boolean;
  internal: boolean;
  required: boolean;
  options: string[];
}

export interface KindSpec {
  kind: Kind;
  label: string;
  prefix: string;
  // 'any' = multi-select over the WHOLE directory - an RFI's answer can
  // come from a client's engineer, a consultant or a supplier.
  recipient: 'multi' | 'single' | 'client' | 'none' | 'any';
  evidence_section: string;
  intro: string;
  fields: FieldSpec[];
  flow: { t: string; name: string; owner?: string; branches?: Record<string, string[]> }[];
  // `branches` rides along on a route: {label: [step names that path adds]}.
  actions: { t: string; name: string; owner?: string; branches?: Record<string, string[]> }[];
}

export interface StepRow {
  id: string;
  position: number;
  type: 'step' | 'gate' | 'route';
  name: string;
  owner: string;
  state: 'open' | 'done' | 'not_required';
  branches: string[];
  chosen_branch: string | null;
  completed_at: string | null;
  completed_by: string | null;
  /** The signer's NAME, resolved server-side. Falls back to the id. */
  completed_by_name?: string | null;
  override_reason: string | null;
  raises_kind: Kind | null;
  raised_reference: string | null;
}

export interface RegisterItemRowBase {
  id: string;
  project_id: string;
  kind: Kind;
  reference: string;
  title: string;
  status: RegisterStatus;
  due_date: string | null;
  days_until_due: number | null;
  is_overdue: boolean;
  fields: Record<string, string>;
  recipient_contact_ids: string[];
  raised_from_id: string | null;
  linked_entity_type: string | null;
  linked_entity_id: string | null;
  steps_total: number;
  steps_done: number;
  current_step: string | null;
  ball_in_court: 'us' | 'them';
  /** WHO it has been put on, assigned - beside the derived side above. */
  ball_in_court_name?: string;
  responsible?: string;
  steps: StepRow[];
  created_at: string | null;
  /**
   * Set only on a withdrawn item. OPTIONAL on purpose: a server that has
   * not shipped the withdraw rail yet simply omits them, and every reader
   * below treats "no reason" as "not withdrawn" rather than crashing.
   */
  withdrawn_reason?: string | null;
  withdrawn_at?: string | null;
  withdrawn_by?: string | null;
}

export interface RegisterItemRow extends RegisterItemRowBase {
  /** Live facts from the platform's own register behind this item. */
  native?: NativeFacts;
}

export type Summary = Record<Kind, { total: number; open: number; overdue: number; with_them: number }>;

export interface Prefill {
  kind: Kind;
  raised_from_id: string;
  raised_from_reference: string;
  title: string;
  fields: Record<string, string>;
  recipient_contact_ids: string[];
}

const BASE = '/v1/register-workflow';

export function fetchSpec(): Promise<{ kinds: Kind[]; specs: Record<Kind, KindSpec> }> {
  return apiGet(`${BASE}/spec`);
}

/** Every list route here answers with a page envelope. */
interface RegisterPage<T> {
  items?: T[];
  total?: number;
}

export async function fetchItems(
  projectId: string,
  kind?: Kind,
  status?: 'open' | 'closed',
): Promise<RegisterItemRow[]> {
  const qs = new URLSearchParams({ project_id: projectId });
  if (kind) qs.set('kind', kind);
  if (status) qs.set('status', status);
  return (await apiGet<RegisterPage<RegisterItemRow>>(`${BASE}/items?${qs.toString()}`)).items ?? [];
}

export function fetchSummary(projectId: string): Promise<Summary> {
  return apiGet(`${BASE}/summary?project_id=${encodeURIComponent(projectId)}`);
}

export function fetchItem(itemId: string): Promise<RegisterItemRow> {
  return apiGet(`${BASE}/items/${encodeURIComponent(itemId)}`);
}

// ── Reverse lookup: native row -> register item ──────────────────────────

/** The native registers an item can mirror (see backend native.py). */
export type LinkedEntityType = 'rfi' | 'rfq' | 'order' | 'variation';

/** One row of `GET /linked`: the register item standing behind a native record. */
export interface LinkedItem {
  item_id: string;
  reference: string;
  kind: Kind;
  status: RegisterStatus;
  title: string;
  due_date: string | null;
  is_overdue: boolean;
  /** The native row's id - the key a base page decorates its rows by. */
  linked_entity_id: string;
  ball_in_court: 'us' | 'them';
}

/**
 * Which register items stand behind these native rows, for a whole page in
 * one call. `ids` narrows to the rows on screen; omit it for the project.
 */
export async function fetchLinkedItems(
  projectId: string,
  entityType: LinkedEntityType,
  ids?: string[],
): Promise<LinkedItem[]> {
  const qs = new URLSearchParams({ project_id: projectId, entity_type: entityType });
  if (ids) qs.set('entity_ids', ids.join(','));
  return (await apiGet<RegisterPage<LinkedItem>>(`${BASE}/linked?${qs.toString()}`)).items ?? [];
}

/**
 * Where a register chip lands: the workspace, opened on that item. An RFQ
 * lands on its compare columns, which is where the question about a
 * package ("who has quoted?") is answered.
 */
export function registerItemUrl(itemId: string, kind?: Kind | string | null): string {
  const qs = new URLSearchParams({ item: itemId });
  if (kind === 'rfq') qs.set('tab', 'compare');
  return `/comms-intelligence?${qs.toString()}`;
}

export function raiseItem(body: {
  project_id: string;
  kind: Kind;
  title: string;
  fields: Record<string, string>;
  recipient_contact_ids: string[];
  raised_from_id?: string | null;
}): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/items`, body);
}

export function updateItem(
  itemId: string,
  body: { title?: string; fields?: Record<string, string>; recipient_contact_ids?: string[] },
): Promise<RegisterItemRow> {
  return apiPatch(`${BASE}/items/${itemId}`, body);
}

// -- Removing something raised in error: delete, or withdraw ------------
//
// TWO TIERS, and the difference is whether anybody outside the building
// has seen it. Nothing sent, no quotes, no replies, nothing raised from
// it -> DELETE, it never really existed. Anything else -> WITHDRAW: it
// stays on the record, marked withdrawn with a written reason, and drops
// out of the open lists. The server owns both rails; this client just
// has to read its refusal honestly.

/** The structured 409 a refused DELETE answers with. */
export interface RemoveRefusal {
  /** The sentence to lead with - "REG-RFQ-... has already gone out." */
  error: string;
  /** Why it cannot be deleted, one line each. May be empty. */
  reasons: string[];
}

/** Delete an item that nobody has seen. 204, or 409 with a RemoveRefusal. */
export function deleteItem(itemId: string): Promise<void> {
  return apiDelete(`${BASE}/items/${encodeURIComponent(itemId)}`);
}

/**
 * Withdraw an item that HAS been seen. The reason is required and is
 * validated server-side, so a junk answer ("x", "n/a") comes back as a
 * refusal to be re-asked with - never assume the first answer took.
 */
export function withdrawItem(itemId: string, reason: string): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/items/${encodeURIComponent(itemId)}/withdraw`, { reason });
}

/**
 * Read a refused delete. Returns undefined when the failure was NOT the
 * two-tier refusal (a 404, a 500, the network) - those are real errors
 * and must not be turned into a withdraw prompt.
 *
 * Defensive on both axes, because the endpoint is newer than this code:
 * the detail may be a plain string rather than the documented object, and
 * a 409 with no machine-readable reasons still means "cannot delete".
 */
export function removeRefusal(e: unknown): RemoveRefusal | undefined {
  const detail = errorDetail<{ error?: string; reasons?: unknown }>(e);
  const reasons = Array.isArray(detail?.reasons)
    ? detail.reasons.map((r) => String(r).trim()).filter(Boolean)
    : [];
  const status = (e as { status?: number } | undefined)?.status;
  if (status !== 409 && reasons.length === 0) return undefined;
  const error = typeof detail?.error === 'string' ? detail.error.trim() : '';
  return { error: error || (e as Error)?.message || '', reasons };
}

/** Withdrawn, however the payload says so - status, or the stamp alone. */
export function isWithdrawn(item: {
  status?: string;
  withdrawn_at?: string | null;
  withdrawn_reason?: string | null;
}): boolean {
  return item.status === 'withdrawn' || !!item.withdrawn_at || !!item.withdrawn_reason;
}

export function fetchPrefill(itemId: string, kind: Kind): Promise<Prefill> {
  return apiGet(`${BASE}/items/${itemId}/prefill/${kind}`);
}

export function addStep(
  itemId: string,
  name: string,
  stepType: 'step' | 'gate' | 'route',
  // WITHOUT A POSITION the server falls back to "after the last finished
  // step", which on an item you are part-way through inserts the new
  // action BEFORE the one you are standing on. The caller knows where
  // the person actually is; it just never said.
  afterPosition?: number,
  branches?: Record<string, string[]>,
): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/items/${itemId}/steps`, {
    name,
    step_type: stepType,
    after_position: afterPosition ?? null,
    branches: branches ?? {},
  });
}

/**
 * The structured refusal a gate/award sends back, wherever the transport
 * put it. The server answers 409 with ``{detail: {error, can_force, ...}}``
 * and the shared client wraps that whole body inside ``ApiError.body`` -
 * reading ``e.detail`` directly finds nothing, which silently killed every
 * "pass the gate anyway?" popup: the refusal toasted and the override was
 * unreachable. One accessor, used by every gate call site, so the shape
 * can only be wrong in one place.
 */
export function errorDetail<
  T extends object = { can_force?: boolean; error?: string; reason_rejected?: boolean },
>(e: unknown): T | undefined {
  const direct = (e as { detail?: T })?.detail;
  if (direct && typeof direct === 'object') return direct;
  const body = (e as { body?: { detail?: T } })?.body;
  if (body?.detail && typeof body.detail === 'object') return body.detail;
  return undefined;
}

export function completeStep(stepId: string, overrideReason?: string): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/steps/${stepId}/complete`, { override_reason: overrideReason ?? null });
}

export function uncompleteStep(stepId: string): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/steps/${stepId}/uncomplete`);
}

export function notRequiredStep(stepId: string): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/steps/${stepId}/not-required`);
}

export function takeRoute(stepId: string, branch: string): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/steps/${stepId}/route`, { branch });
}

// Suppliers / contacts for the addressing-first picker.
export interface ContactRow {
  id: string;
  company_name: string | null;
  first_name: string | null;
  last_name: string | null;
  primary_email: string | null;
  primary_phone?: string | null;
  contact_type: string;
}

export function searchContacts(search: string, contactType?: string): Promise<ContactRow[]> {
  // The directory has a dedicated full-text endpoint taking `q`; the plain
  // list endpoint ignores a `search` param and would return the first 25
  // rows whatever you typed, which reads as "search is broken".
  const qs = new URLSearchParams({ limit: '25' });
  if (contactType) qs.set('contact_type', contactType);
  const path = search.trim()
    ? `/v1/contacts/search/?q=${encodeURIComponent(search.trim())}&${qs.toString()}`
    : `/v1/contacts/?${qs.toString()}`;
  return apiGet<{ items: ContactRow[] } | ContactRow[]>(path).then((r) =>
    Array.isArray(r) ? r : (r.items ?? []),
  );
}

// ── Native enrichment: the item IS the platform's own record ─────────────

export interface NativeBid {
  id: string;
  bidder_contact_id: string;
  amount: string;
  currency: string;
  status: string;
  is_awarded: boolean;
  notes: string;
  submitted_at: string | null;
}

export interface QuoteGate {
  value: string;
  required: number;
  counted: number;
  quoted_suppliers: string[];
  rule: Record<string, string>;
  passes: boolean;
}

export interface NativeFacts {
  native?: string;
  rfq_number?: string;
  rfq_status?: string;
  currency?: string;
  quote_gate?: QuoteGate;
  bids?: NativeBid[];
  award?: {
    bid_id: string;
    reason: string | null;
    amount: string;
    currency: string;
    is_override: boolean;
    po_number: string | null;
    quote_gate: QuoteGate | null;
    awarded_at: string;
  } | null;
  rfi_number?: string;
  rfi_status?: string;
  official_response?: string | null;
  code?: string;
  variation_status?: string;
  po_number?: string;
  amount_total?: string;
  delivery_date?: string | null;
}

export const AWARD_REASONS = [
  'Best price',
  'Best lead time',
  'Best price and lead time',
  'Only supplier who quoted',
  'Technical compliance',
  'Preferred supplier / rates agreement',
  'Previous experience on this site',
  'Client directed',
  'Availability - others could not meet the program',
];

export function recordQuote(
  itemId: string,
  body: { bidder_contact_id: string; amount: string; lead_time?: string; quote_number?: string; notes?: string },
): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/items/${itemId}/quotes`, body);
}

export function awardItem(
  itemId: string,
  body: { bid_id: string; reason: string; po_number?: string; gate_override_reason?: string },
): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/items/${itemId}/award`, body);
}

export function fetchContactsByIds(ids: string[]): Promise<ContactRow[]> {
  if (ids.length === 0) return Promise.resolve([]);
  return apiGet<{ items: ContactRow[] } | ContactRow[]>(`/v1/contacts/?limit=500`).then((r) => {
    const all = Array.isArray(r) ? r : (r.items ?? []);
    const want = new Set(ids.map(String));
    return all.filter((c) => want.has(String(c.id)));
  });
}

// ── Item emails, attachments, thread ─────────────────────────────────────

export interface ItemEmailPreview {
  item_id: string;
  reference_number: string;
  contact_id: string | null;
  contact_name: string;
  to: string[];
  cc: string[];
  subject: string;
  html: string;
  notified: { name: string; date: string }[];
}

export interface ThreadEntry {
  type: 'send' | 'correspondence';
  at: string | null;
  who?: string;
  subject: string;
  channel?: string;
  email_ref?: string;
  id?: string;
  direction?: string;
  reference?: string;
  status?: string;
  category?: string | null;
  confidence?: number | null;
  /** The body exactly as it went out. Empty for sends logged after the fact. */
  html?: string;
  contact_id?: string | null;
}

export interface SendLogEntry {
  at: string;
  contact_id: string | null;
  contact_name: string;
  subject: string;
  channel: string;
}

export function previewItemEmail(
  itemId: string,
  contactId: string | null,
  // These two were hard-coded empty here, so the backend's support for
  // both was unreachable: there was no way to copy anyone in, and no way
  // to say anything to this supplier that was not already a field.
  extraTo: string[] = [],
  extraNote = '',
): Promise<ItemEmailPreview> {
  return apiPost(`${BASE}/items/${itemId}/email/preview`, {
    contact_id: contactId,
    extra_to: extraTo,
    extra_note: extraNote,
  });
}

export function draftItemEmail(
  itemId: string,
  contactId: string | null,
  extraTo: string[] = [],
  extraNote = '',
): Promise<{ opened: number; item: RegisterItemRow }> {
  // contactId null on a multi-recipient item = DRAFT ALL.
  return apiPost(
    `${BASE}/items/${itemId}/email/draft`,
    { contact_id: contactId, extra_to: extraTo, extra_note: extraNote },
    { longRunning: true },
  );
}

export async function downloadItemEml(itemId: string, contactId: string | null, reference: string): Promise<void> {
  const { useAuthStore } = await import('@/stores/useAuthStore');
  const token = useAuthStore.getState().accessToken;
  const res = await fetch(`/api${BASE}/items/${itemId}/email/eml`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ contact_id: contactId, extra_to: [] }),
  });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${reference}.eml`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Award confirmation to the winning supplier ───────────────────────────

export interface AwardConfirmBody {
  contact_id: string;
  po_number?: string;
  amount?: string;
  note?: string;
}

/** Preview the order-confirmation email to the winner. Server-rendered, so it
 *  works with no mailbox bridge. Byte-for-byte what the .eml carries. */
export function previewAwardConfirmation(
  itemId: string,
  body: AwardConfirmBody,
): Promise<ItemEmailPreview> {
  return apiPost(`${BASE}/items/${itemId}/award-confirmation/preview`, body);
}

/** Download the order confirmation as an editable .eml (open it, press Send).
 *  Downloading is logged as a send on the item. */
export async function downloadAwardConfirmationEml(
  itemId: string,
  body: AwardConfirmBody,
  reference: string,
): Promise<void> {
  const { useAuthStore } = await import('@/stores/useAuthStore');
  const token = useAuthStore.getState().accessToken;
  const res = await fetch(`/api${BASE}/items/${itemId}/award-confirmation/eml`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${reference}-confirmation.eml`;
  a.click();
  URL.revokeObjectURL(url);
}

export async function uploadItemAttachment(itemId: string, file: globalThis.File): Promise<RegisterItemRow> {
  const { useAuthStore } = await import('@/stores/useAuthStore');
  const token = useAuthStore.getState().accessToken;
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`/api${BASE}/items/${itemId}/attachments`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) throw new Error(`Upload failed (${res.status})`);
  return res.json();
}

export async function fetchItemThread(itemId: string): Promise<ThreadEntry[]> {
  return (await apiGet<RegisterPage<ThreadEntry>>(`${BASE}/items/${itemId}/thread`)).items ?? [];
}

export function updateContact(
  contactId: string,
  body: { company_name?: string; primary_email?: string; primary_phone?: string; first_name?: string; last_name?: string },
): Promise<ContactRow> {
  return apiPatch(`/v1/contacts/${contactId}/`, body);
}

export function setProjectJobNumber(
  projectId: string,
  code: string,
): Promise<{ id: string; project_code: string | null }> {
  // The native projects endpoint, on purpose: ownership/admin is verified
  // there, and the raise gate re-validates the number server-side on the
  // next preview - this is a shortcut to the same field, not a second rail.
  return apiPatch(`/v1/projects/${projectId}`, { project_code: code });
}

export function previewComposeEmail(body: {
  project_id: string;
  kind: Kind;
  title: string;
  fields: Record<string, string>;
  recipient_contact_ids: string[];
  contact_id: string | null;
}): Promise<ItemEmailPreview & { peeked_reference: string }> {
  return apiPost(`${BASE}/preview-email`, body);
}

// ── Suggestions, documents, stats, configurator ──────────────────────────

export interface SuggestionEntry {
  correspondence_id: string;
  reference: string;
  subject: string;
  received: string | null;
  amount: string | null;
  basis: string | null;
  evidence: string | null;
  lead_time: string;
  quote_number: string | null;
  reply_kind: string | null;
  confidence: number;
}

export interface Suggestions {
  by_supplier: Record<string, { latest: SuggestionEntry | null; superseded: SuggestionEntry[] }>;
  unmatched: SuggestionEntry[];
}

export interface RegisterStats {
  open: number;
  closed: number;
  avg_days_to_close: number | null;
  closed_on_time_pct: number | null;
  oldest_open_days: number | null;
  oldest_open_reference: string | null;
  lost_hours: string;
}

export interface PortfolioRow {
  project_id: string;
  project_name: string;
  open: number;
  overdue: number;
  with_them: number;
}

export function fetchSuggestions(itemId: string): Promise<Suggestions> {
  return apiGet(`${BASE}/items/${itemId}/suggestions`);
}

export function fetchStats(projectId: string): Promise<RegisterStats> {
  return apiGet(`${BASE}/stats?project_id=${encodeURIComponent(projectId)}`);
}

export async function fetchPortfolio(): Promise<PortfolioRow[]> {
  return (await apiGet<RegisterPage<PortfolioRow>>(`${BASE}/portfolio`)).items ?? [];
}

export function documentUrl(itemId: string, filename: string): string {
  return `/api${BASE}/items/${itemId}/documents/${encodeURIComponent(filename)}`;
}

export function setAttachmentEmailFlag(itemId: string, filename: string, email: boolean): Promise<RegisterItemRow> {
  return apiPatch(`${BASE}/items/${itemId}/attachments`, { filename, email });
}

/** One row of the rewritten to-do list. A name already open on the item is
 *  KEPT as it is (its own type, owner and branches - `type`/`branches` are
 *  ignored for it); anything else is new. A new `route` must carry its
 *  `branches` ({label: [step names that path adds]}) or the server refuses. */
export interface RemainingStep {
  name: string;
  type: 'step' | 'gate' | 'route';
  owner?: string;
  branches?: Record<string, string[]>;
}

export function configureSteps(
  itemId: string,
  remaining: RemainingStep[],
  retireReason?: string,
): Promise<RegisterItemRow> {
  // `retire_reason` is only read when a gate or a decision is being taken
  // off the workflow — the server refuses that without one, and records
  // the hold point as retired rather than deleting it.
  return apiPost(`${BASE}/items/${itemId}/configure`, {
    remaining,
    retire_reason: retireReason ?? '',
  });
}

export function logAlreadySent(
  itemId: string,
  body: { contact_id?: string | null; contact_name?: string; sent_on?: string },
): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/items/${itemId}/log-sent`, body);
}

/** Manually file a reply/response against an item, for a deployment with no
 *  mailbox bridge. The server reuses the same inbound-capture path the bridge
 *  uses, so the reply lands on the item's thread and flips the sender's
 *  tracking row to "replied" (or "quoted" when the body carries a price). */
export function logReply(
  itemId: string,
  body: {
    contact_id?: string | null;
    from_name?: string;
    from_email?: string;
    subject?: string;
    body?: string;
    received_on?: string;
  },
): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/items/${itemId}/log-reply`, body);
}

// ── Email tracking, side-by-side comparison, reading a reply ─────────────

export type TrackState = 'not_asked' | 'waiting' | 'chase' | 'overdue' | 'replied' | 'quoted';

export interface TrackRow {
  contact_id: string | null;
  name: string;
  email: string;
  sent_count: number;
  first_sent_at: string | null;
  last_sent_at: string | null;
  channels: string[];
  last_subject: string | null;
  chases: number;
  replied_at?: string | null;
  reply_subject?: string | null;
  reply_reference?: string | null;
  correspondence_id?: string | null;
  reply_count?: number;
  quoted_amount?: string;
  quoted_basis?: string;
  days_waiting: number | null;
  days_to_reply: number | null;
  state: TrackState;
  ad_hoc?: boolean;
}

export interface ItemTracking {
  reference: string;
  kind: Kind;
  title: string;
  rows: TrackRow[];
  totals: {
    asked: number;
    on_the_list: number;
    replied: number;
    quoted: number;
    silent: number;
    overdue: number;
    never_asked: number;
  };
}

export interface ProjectTracking {
  outstanding: (TrackRow & { item_id: string; reference: string; kind: Kind; title: string; due_date: string | null })[];
  totals: { emails_sent: number; awaiting_reply: number; to_chase: number; overdue: number };
}

export interface CompareDoc {
  filename: string;
  is_quote_document: boolean;
  inline: boolean;
  correspondence_id: string;
}

export interface CompareColumn {
  contact_id: string | null;
  name: string;
  email: string;
  state: TrackState;
  days_waiting: number | null;
  sent_count: number;
  replied_at: string | null;
  amount: string;
  basis: string;
  lead_time: string;
  quote_number: string;
  evidence: string;
  warnings: string[];
  reply_subject: string | null;
  reply_body: string;
  /** The reply's formatted original - sanitised SERVER-SIDE at capture. */
  reply_html?: string;
  documents: CompareDoc[];
  has_quote_document: boolean;
}

export interface SideBySide {
  item_id: string;
  reference: string;
  kind: Kind;
  title: string;
  columns: CompareColumn[];
  totals: ItemTracking['totals'];
}

export interface MessageParty {
  contact_id: string;
  name: string;
  email: string;
}

export interface ExtractedFacts {
  amount?: string;
  basis?: string;
  evidence?: string;
  warnings?: string[];
  lead_time?: string;
  quote_number?: string;
  category?: string;
  confidence?: number | null;
}

export interface ViewedMessage {
  correspondence_id: string;
  reference_number: string;
  subject: string;
  direction: string;
  date: string | null;
  from_people: MessageParty[];
  to_people: MessageParty[];
  text: string;
  html: string;
  remote_content_blocked: boolean;
  documents: (CompareDoc & { size?: number })[];
  extracted?: ExtractedFacts;
}

export function fetchItemTracking(itemId: string): Promise<ItemTracking> {
  return apiGet(`${BASE}/items/${itemId}/tracking`);
}

export function fetchProjectTracking(projectId: string): Promise<ProjectTracking> {
  return apiGet(`${BASE}/tracking?project_id=${encodeURIComponent(projectId)}`);
}

export function fetchSideBySide(itemId: string): Promise<SideBySide> {
  return apiGet(`${BASE}/items/${itemId}/compare`);
}

export function fetchMessage(itemId: string, correspondenceId: string): Promise<ViewedMessage> {
  return apiGet(`${BASE}/items/${itemId}/messages/${correspondenceId}`);
}

/** Proxied through the API so the browser never needs a storage key. */
/**
 * Announce what has newly fallen due, onto the platform's own bus.
 *
 * A POST because it writes: each reason is remembered so it fires at
 * most once per item per day. Without that the 45-second poll would
 * republish the same overdue RFI every 45 seconds until somebody
 * silenced the bell for good.
 */
export function deadlineSweep(projectId: string): Promise<{ published: number; detail: string[] }> {
  return apiPost(`${BASE}/deadline-sweep?project_id=${encodeURIComponent(projectId)}`);
}

export interface FieldSuggestions {
  kind: string;
  /** label -> what to pre-fill, and what this job has used before. */
  fields: Record<string, { default: string; recent: string[] }>;
  project_address: string;
}

/**
 * Defaults and this job's own history, per field.
 *
 * Project-scoped on purpose: a delivery address from another job is not
 * a helpful suggestion, it is a way to send switchboards to the wrong
 * site.
 */
export function fetchFieldSuggestions(projectId: string, kind: string): Promise<FieldSuggestions> {
  return apiGet(
    `${BASE}/field-suggestions?project_id=${encodeURIComponent(projectId)}&kind=${encodeURIComponent(kind)}`,
  );
}

export interface ItemLink {
  type: 'item' | 'cost_centre' | 'deliverable' | 'url';
  label: string;
  target_id?: string;
  reference?: string;
}

export function linksOf(item: RegisterItemRow): ItemLink[] {
  const raw = (item.fields as Record<string, unknown>)?._links;
  return Array.isArray(raw) ? (raw as ItemLink[]) : [];
}

export function addItemLink(
  itemId: string,
  linkType: ItemLink['type'],
  value: string,
): Promise<{ links: ItemLink[] }> {
  return apiPost(`${BASE}/items/${itemId}/links`, { link_type: linkType, value });
}

export function removeItemLink(itemId: string, index: number): Promise<{ links: ItemLink[] }> {
  return apiPost(`${BASE}/items/${itemId}/links/remove`, { index });
}

export interface SupplierRanking {
  kind: string;
  /** contact id -> which tier it earned and the words for it. */
  tiers: Record<string, { tier: number; label: string }>;
  tier_labels: Record<string, string>;
  recent_days: number;
}

/**
 * Which suppliers to float to the top of the picker.
 *
 * Computed on the server: "recent" and "on this job" are facts about the
 * data, and a 434-company directory cannot be ranked from the 40 rows a
 * search happened to return.
 */
export function fetchSupplierRanking(projectId: string, kind: string): Promise<SupplierRanking> {
  return apiGet(
    `${BASE}/supplier-ranking?project_id=${encodeURIComponent(projectId)}&kind=${encodeURIComponent(kind)}`,
  );
}

export type ReplyMode = 'reply' | 'reply_all' | 'forward';

export interface BuiltReply {
  mode: ReplyMode;
  correspondence_id: string;
  to: string[];
  subject: string;
  html: string;
  attachment_names: string[];
  in_reply_to: { subject: string; from: string; date: string; reference_number: string };
  opened?: boolean;
  error?: string;
}

/** What the draft WILL be. Same builder as openReplyDraft - never a second one. */
export function previewReply(
  itemId: string,
  correspondenceId: string,
  body: { mode: ReplyMode; to: string[]; body: string },
): Promise<BuiltReply> {
  return apiPost(`${BASE}/items/${itemId}/messages/${correspondenceId}/reply-preview`, body);
}

/** Opens it in Outlook. Nothing is sent from here - the user presses Send there. */
export function openReplyDraft(
  itemId: string,
  correspondenceId: string,
  body: { mode: ReplyMode; to: string[]; body: string },
): Promise<BuiltReply> {
  return apiPost(`${BASE}/items/${itemId}/messages/${correspondenceId}/reply-draft`, body);
}

export function messageDocumentUrl(itemId: string, correspondenceId: string, filename: string): string {
  return `/api/v1/register-workflow/items/${itemId}/messages/${correspondenceId}/documents/${encodeURIComponent(filename)}`;
}

export function logAlreadySentMany(
  itemId: string,
  entries: { contact_id?: string | null; contact_name?: string; sent_on?: string }[],
): Promise<RegisterItemRow> {
  return apiPost(`${BASE}/items/${itemId}/log-sent-many`, { entries });
}
