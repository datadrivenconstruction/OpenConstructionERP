// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Punch List.
 *
 * All endpoints are prefixed with /v1/punchlist/.
 */

import {
  API_BASE,
  apiGet,
  apiPost,
  apiPatch,
  apiDelete,
  downloadWithAuth,
  type Page,
} from '@/shared/lib/api';
import { listRoster, type RosterMember } from '@/features/teams/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type PunchPriority = 'low' | 'medium' | 'high' | 'critical';
// Full lifecycle FSM mirrored from the backend (punchlist/service.py
// VALID_TRANSITIONS): open -> assigned -> in_progress -> resolved ->
// verified -> closed, and any state can go back to open (reopen). The
// 'assigned' stage lets a snag be owned before work actually starts.
export type PunchStatus =
  | 'open'
  | 'assigned'
  | 'in_progress'
  | 'resolved'
  | 'verified'
  | 'closed';
export type PunchCategory =
  | 'structural'
  | 'mechanical'
  | 'electrical'
  | 'architectural'
  | 'plumbing'
  | 'finishing'
  | 'fire_safety'
  | 'hvac'
  | 'exterior'
  | 'landscaping'
  | 'general';

export interface PunchItem {
  id: string;
  project_id: string;
  title: string;
  description: string;
  priority: PunchPriority;
  status: PunchStatus;
  category: PunchCategory | null;
  assigned_to: string | null;
  /** Name of the contact `assigned_to` holds the id of, when it holds one. */
  assigned_to_name: string | null;
  due_date: string | null;
  document_id: string | null;
  page: number | null;
  location_x: number | null;
  location_y: number | null;
  photos: string[];
  trade: string | null;
  resolution_notes: string | null;
  verified_by: string | null;
  /** Name of the contact `verified_by` holds the id of, when it holds one. */
  verified_by_name: string | null;
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  verified_at: string | null;
  reopen_history?: ReopenHistoryEntry[];
  /**
   * What it costs to put the item right, as a decimal string, or null when
   * nobody has priced it (which is not zero). QMS counts it into the cost of
   * poor quality, and it is the open-items value a retainage release at
   * substantial completion holds money back against.
   */
  rework_cost: string | null;
  /** ISO code the cost is in. Rendered as stored, never relabelled. */
  rework_cost_currency: string;
}

export interface ReopenHistoryEntry {
  reopened_at: string;
  reopened_by: string | null;
  previous_status: string;
  reason?: string;
}

export interface BulkCloseResponse {
  closed: number;
  skipped: number;
  errors: { id: string; error: string }[];
}

/**
 * Project-wide punch list aggregates.
 *
 * Every number here is counted over the whole project by the server. The KPI
 * band reads it instead of deriving figures from a page of rows, which is
 * what it used to do and which went wrong the moment a project outgrew one
 * page.
 */
export interface PunchSummary {
  total: number;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  overdue: number;
  avg_days_to_close: number | null;
  /** Critical or high priority items still open or in progress. */
  urgent_open: number;
  /** Items closed or verified in the last seven days. */
  closed_last_7_days: number;
  /** Mean age in days of items still open, null when none are. */
  avg_open_age_days: number | null;
}

export interface PunchFilters {
  /**
   * Free-text search. NOT sent anywhere useful today: the backend list route
   * declares no `search` query param, so FastAPI drops it and the register
   * filters client-side over the page it already holds. Kept so the call
   * sites do not change when the server learns to search.
   */
  search?: string;
  priority?: PunchPriority | '';
  status?: PunchStatus | '';
  category?: PunchCategory | '';
  assigned_to?: string;
  /** Rows per page. Server default 50, hard cap 100. */
  limit?: number;
}

export interface CreatePunchPayload {
  project_id: string;
  title: string;
  description?: string;
  priority?: PunchPriority;
  category?: PunchCategory;
  assigned_to?: string;
  due_date?: string;
  document_id?: string;
  /** 1-based sheet page the pin sits on (backend accepts page>=1). */
  page?: number;
  location_x?: number | null;
  location_y?: number | null;
  trade?: string;
  /** Decimal string with a dot, e.g. "1250.5". */
  rework_cost?: string;
  /** Send the project's currency: the backend defaults to USD otherwise. */
  rework_cost_currency?: string;
}

export interface UpdatePunchPayload {
  title?: string;
  description?: string;
  priority?: PunchPriority;
  category?: PunchCategory;
  assigned_to?: string | null;
  due_date?: string | null;
  document_id?: string | null;
  location_x?: number | null;
  location_y?: number | null;
  trade?: string | null;
  resolution_notes?: string | null;
  /** null clears the price. */
  rework_cost?: string | null;
  /** Never null: the column is NOT NULL and the API refuses it. Omit to keep. */
  rework_cost_currency?: string;
}

export interface TeamMember {
  /**
   * The value written to `assigned_to`. Always a user id for anybody who can
   * be assigned; a `roster:` sentinel for the people who cannot, so a stray
   * write is visible rather than silently unresolvable.
   */
  id: string;
  name: string;
  email: string;
  avatar_url: string | null;
  /** Firm and site role, for telling two people with the same name apart. */
  detail?: string;
  /** False for a person on the roster who holds no account. */
  assignable?: boolean;
  /** True for somebody written down on this project, false for the rest of the workspace. */
  on_roster?: boolean;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

/**
 * Fetch one page of the project's punch items.
 *
 * Returns the whole `{items, total, offset, limit}` envelope rather than just
 * the rows: `total` counts every item matching the filters, so a caller can
 * tell it is holding a slice and say so. Callers that only need the rows read
 * `.items`, but they have to do it themselves, which is the point.
 *
 * `limit` defaults to the server's 50 and is capped there at 100.
 */
export async function fetchPunchItems(
  projectId: string,
  filters?: PunchFilters,
): Promise<Page<PunchItem>> {
  if (!projectId) return { items: [], total: 0, offset: 0, limit: 0 };
  const params = new URLSearchParams({ project_id: projectId });
  if (filters?.search) params.set('search', filters.search);
  if (filters?.priority) params.set('priority', filters.priority);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.category) params.set('category', filters.category);
  if (filters?.assigned_to) params.set('assigned_to', filters.assigned_to);
  if (filters?.limit != null) params.set('limit', String(filters.limit));
  return apiGet<Page<PunchItem>>(`/v1/punchlist/items/?${params.toString()}`);
}

export async function createPunchItem(data: CreatePunchPayload): Promise<PunchItem> {
  return apiPost<PunchItem>('/v1/punchlist/items/', data);
}

export async function updatePunchItem(id: string, data: UpdatePunchPayload): Promise<PunchItem> {
  return apiPatch<PunchItem>(`/v1/punchlist/items/${id}`, data);
}

export async function deletePunchItem(id: string): Promise<void> {
  return apiDelete(`/v1/punchlist/items/${id}`);
}

export async function transitionPunchStatus(
  id: string,
  newStatus: PunchStatus,
  notes?: string,
): Promise<PunchItem> {
  // `notes` is optional and, when present, is stored by the backend as the
  // resolution note (or the reopen reason on a reopen). Existing callers that
  // pass only (id, status) are unaffected.
  const body: { new_status: PunchStatus; notes?: string } = { new_status: newStatus };
  const trimmed = notes?.trim();
  if (trimmed) body.notes = trimmed;
  return apiPost<PunchItem>(`/v1/punchlist/items/${id}/transition/`, body);
}

/** Fetch a single punch item by id (used by the detail drawer to stay fresh). */
export async function fetchPunchItem(id: string): Promise<PunchItem> {
  return apiGet<PunchItem>(`/v1/punchlist/items/${id}`);
}

export async function bulkClose(
  ids: string[],
  projectId: string,
  comment?: string,
): Promise<BulkCloseResponse> {
  return apiPost<BulkCloseResponse>('/v1/punchlist/bulk-close/', {
    ids,
    project_id: projectId,
    comment,
  });
}

export async function uploadPunchPhoto(id: string, file: File): Promise<PunchItem> {
  const formData = new FormData();
  formData.append('file', file);
  const token = localStorage.getItem('oe_access_token');
  const res = await fetch(`/api/v1/punchlist/items/${id}/photos/`, {
    method: 'POST',
    headers: {
      Authorization: token ? `Bearer ${token}` : '',
      'X-DDC-Client': 'OE/1.0',
    },
    body: formData,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
  return res.json();
}

/** Remove a photo from a punch item by its index in the photos array. */
export async function deletePunchPhoto(id: string, index: number): Promise<void> {
  return apiDelete(`/v1/punchlist/items/${id}/photos/${index}`);
}

/** Payload for pinning a punch item to a location on a drawing sheet. */
export interface PinToSheetPayload {
  /** Document (drawing) the pin sits on. */
  document_id?: string;
  /** Sheet id, accepted by the backend as an alternative to document_id. */
  sheet_id?: string;
  /** 1-based page the pin sits on. */
  page: number;
  /** Normalised pin coordinates on the sheet (0..1). */
  location_x: number;
  location_y: number;
}

/**
 * Pin a punch item to a normalised (0..1) location on a drawing sheet.
 * Wraps POST /v1/punchlist/items/{id}/pin-to-sheet/.
 */
export async function pinPunchToSheet(id: string, payload: PinToSheetPayload): Promise<PunchItem> {
  return apiPost<PunchItem>(`/v1/punchlist/items/${id}/pin-to-sheet/`, payload);
}

/** A project document as returned by the documents list endpoint. */
export interface PunchDocument {
  id: string;
  name: string;
  description?: string;
  category?: string;
}

/**
 * Photos uploaded to a punch item are stored as relative paths and
 * cross-linked as Document records (category "photo", name = the stored
 * filename). There is no static route that serves the raw path, so to show a
 * thumbnail we resolve the photo's basename to its cross-linked document and
 * stream that through the authenticated documents download endpoint. This
 * returns the photo-category documents for the project so the caller can build
 * a filename -> document-id map.
 */
export async function fetchPunchPhotoDocuments(projectId: string): Promise<PunchDocument[]> {
  if (!projectId) return [];
  const page = await apiGet<Page<PunchDocument>>(
    `/v1/documents/?project_id=${projectId}&category=photo&limit=500`,
  );
  return page.items;
}

/** A drawing/document option for the pin board and pin picker. */
export interface PunchDrawing {
  id: string;
  filename: string;
}

/** List the project documents that can be used as pin-board drawings. */
export async function fetchPunchDrawings(projectId: string): Promise<PunchDrawing[]> {
  if (!projectId) return [];
  const page = await apiGet<Page<{ id: string; filename?: string; name?: string }>>(
    `/v1/documents/?project_id=${projectId}&limit=500`,
  );
  return page.items.map((r) => ({
    id: r.id,
    filename: r.filename ?? r.name ?? '',
  }));
}

/**
 * Download the project's punch list as a PDF, printed on the company
 * letterhead when one is set.
 *
 * Route is GET /export/pdf/ WITH a trailing slash (router.py). No ?locale= is
 * sent, unlike the RFI export: the route takes none, because its headings are
 * English literals in the service, and it declares Content-Language: en.
 */
export async function downloadPunchListPdf(projectId: string): Promise<void> {
  await downloadWithAuth(
    `${API_BASE}/v1/punchlist/export/pdf/?project_id=${encodeURIComponent(projectId)}`,
    `punchlist_${projectId}.pdf`,
  );
}

export async function fetchPunchSummary(projectId: string): Promise<PunchSummary> {
  if (!projectId)
    return {
      total: 0,
      by_status: {},
      by_priority: {},
      overdue: 0,
      avg_days_to_close: null,
      urgent_open: 0,
      closed_last_7_days: 0,
      avg_open_age_days: null,
    };
  return apiGet<PunchSummary>(`/v1/punchlist/summary/?project_id=${projectId}`);
}

interface UserListEntry {
  id: string;
  email: string;
  full_name?: string | null;
  is_active?: boolean;
}

/**
 * The people who can be handed a snag on this project.
 *
 * Reads the project roster and falls back to the whole workspace. Two things
 * are deliberate:
 *
 * `id` carries the roster line's `user_id`, never the line's own id. This
 * value lands in `punchlist.assigned_to`, a bare `String(36)` with no foreign
 * key, and a roster-line id written there resolves to nobody on every screen
 * that prints an assignee - a silent write, not an error.
 *
 * Roster people with no account come back with `assignable: false` rather than
 * being dropped. Most of a site holds no login, and a foreman who is simply
 * missing from the list reads as a bug; a foreman shown greyed out reads as
 * the fact it is.
 *
 * The fallback triggers on "nobody here can be assigned", not on "the roster
 * is empty" - a roster full of subcontractors without accounts has rows and no
 * assignable person, and that is exactly the project the list must not go
 * blank on.
 */
export async function fetchTeamMembers(projectId: string): Promise<TeamMember[]> {
  if (!projectId) return [];

  const [roster, users] = await Promise.all([
    listRoster(projectId, { includeInactive: false })
      .then((page) => page.items)
      .catch(() => [] as RosterMember[]),
    apiGet<UserListEntry[] | { items: UserListEntry[] }>('/v1/users/?limit=100').catch(
      () => [] as UserListEntry[],
    ),
  ]);

  const list = Array.isArray(users) ? users : users.items ?? [];
  const workspace: TeamMember[] = list
    .filter((u) => u.is_active !== false)
    .map((u) => ({
      id: u.id,
      name: u.full_name?.trim() || u.email,
      email: u.email,
      avatar_url: null,
      assignable: true,
      on_roster: false,
    }));

  // The roster only leads when somebody on it can actually hold a snag. A
  // project whose roster is all subcontractor gangs without accounts has plenty
  // of rows and nobody assignable, and keying on row count instead of on
  // assignability would leave the list empty on exactly that project.
  if (!roster.some((m) => m.user_id && !m.user_is_inactive)) return withDisambiguation(workspace);

  const rostered = new Set(roster.map((m) => m.user_id).filter((id): id is string => !!id));
  const rosterRows: TeamMember[] = roster.map((m) => ({
    id: m.user_id && !m.user_is_inactive ? m.user_id : `roster:${m.id}`,
    name: m.display_name,
    email: m.email,
    avatar_url: null,
    detail: [m.company_name, m.site_role_label || m.trade_label].filter(Boolean).join(' · '),
    assignable: !!m.user_id && !m.user_is_inactive,
    on_roster: true,
  }));

  // Accounts nobody wrote down are kept, after the roster. A snag assigned
  // before anybody filled the roster in points at one of them, and an option
  // that is missing makes the editor read "Unassigned" for an item that is
  // assigned to somebody.
  return withDisambiguation([...rosterRows, ...workspace.filter((u) => !rostered.has(u.id))]);
}

const nameKey = (name: string) => name.trim().replace(/\s+/g, ' ').toLocaleLowerCase();

/**
 * Show an email beside a name only where the name alone is ambiguous.
 *
 * Every account in the picker used to read "Name - email", which put the whole
 * workspace's addresses on screen for anyone opening a snag, and in any screen
 * recording or screen share of it. The name is what a site manager picks by;
 * the address only earns its place when two people in the list share a name
 * and there is nothing else to tell them apart. A roster row keeps its firm and
 * site role, which already does that job without an address.
 */
export function withDisambiguation(members: TeamMember[]): TeamMember[] {
  const counts = new Map<string, number>();
  for (const m of members) counts.set(nameKey(m.name), (counts.get(nameKey(m.name)) ?? 0) + 1);
  return members.map((m) => {
    const shared = (counts.get(nameKey(m.name)) ?? 0) > 1;
    const detail = m.detail || (shared && m.email && nameKey(m.email) !== nameKey(m.name) ? m.email : undefined);
    return { ...m, detail };
  });
}
