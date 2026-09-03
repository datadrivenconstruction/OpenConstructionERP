// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Typed client for the Work Requests backend module
 * (`/api/v1/work-requests`).
 *
 * The contract is fixed with the backend being built alongside this
 * module. Everything a screen needs is a named function here so a test
 * can mock this one file and every screen stays honest about what it
 * sends. Nothing in this file renders.
 */

import { API_BASE, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth, getAuthToken } from '@/shared/lib/api';

/* ── Departments ──────────────────────────────────────────────────── */

export interface Stage {
  key: string;
  name: string;
  colour: string;
  order: number;
  /** Moving a request here closes it (Site as-built, READY FOR FAT). */
  closes: boolean;
}

export type FieldType = 'text' | 'area' | 'date' | 'number' | 'bool' | 'select' | 'url';

export interface RequestField {
  key: string;
  label: string;
  type: FieldType;
  options?: string[];
  required?: boolean;
}

export interface RequestType {
  key: string;
  label: string;
  /** Hours and cost centres are asked per discipline (drafting, testing…). */
  disciplines: string[];
  fields: RequestField[];
  /**
   * A retired type: it stays on the requests that already carry it and
   * disappears from the pickers. Optional because a backend that predates
   * the request-type editor sends neither this nor `position` - absent
   * means active (see `typesOf`).
   */
  active?: boolean;
  /** The order the department wants them offered in. */
  position?: number;
}

/** What `POST`/`PATCH /departments/{key}/request-types` accepts. */
export interface RequestTypeBody {
  /** Server-minted from the label on create; never changes afterwards. */
  key?: string;
  label?: string;
  disciplines?: string[];
  fields?: RequestField[];
  active?: boolean;
}

export interface Department {
  key: string;
  name: string;
  /** The reference token, e.g. `WKS` in `WR-WKS-000012`. Server-owned. */
  prefix: string;
  colour: string;
  description: string;
  active: boolean;
  /** Tab order. Server-owned; `PATCH /departments/{key}` may set it. */
  position: number;
  lead_user_id: string | null;
  member_ids: string[];
  /**
   * Money as Decimal-as-TEXT (`"125.00"`), NOT a number - the whole
   * backend carries money this way. `Number()` it before arithmetic and
   * render it with `fmtMoney`.
   */
  hourly_rate: string | null;
  /**
   * The working days this department promises from acceptance. The server
   * turns it into a request's `target_date` and, past it, `is_late`.
   * Optional: a backend that predates the lateness contract sends neither,
   * and the UI must simply not draw a late pill rather than inventing one.
   */
  target_days?: number | null;
  stages: Stage[];
  request_types: RequestType[];
}

/* ── Requests ─────────────────────────────────────────────────────── */

export type Status =
  | 'draft'
  | 'submitted'
  | 'accepted'
  | 'in_progress'
  | 'on_hold'
  | 'review'
  | 'complete'
  | 'closed'
  | 'cancelled';

export const STATUSES: Status[] = [
  'draft',
  'submitted',
  'accepted',
  'in_progress',
  'on_hold',
  'review',
  'complete',
  'closed',
  'cancelled',
];

export const CLOSED_STATUSES: Status[] = ['complete', 'closed', 'cancelled'];

export type Priority = 'low' | 'normal' | 'high' | 'urgent';
export const PRIORITIES: Priority[] = ['low', 'normal', 'high', 'urgent'];

export type BallInCourt = 'requester' | 'department';

export interface Person {
  id: string;
  name: string;
}

export interface StageHistoryEntry {
  stage: string;
  at: string;
  by_id: string | null;
  by_name: string;
  note: string | null;
}

export interface LinkRef {
  label: string;
  url: string;
}

export interface RelatedRequest {
  id: string;
  reference: string;
  title: string;
  status: Status;
  department: string;
}

export interface Attachment {
  filename: string;
  size: number;
  uploaded_at: string;
}

/**
 * One line of the department's own sign-off list ("Busbars torqued",
 * "Megger test recorded"). `required` items gate a closing stage: the
 * server refuses the move with a 409 that NAMES the outstanding ones, and
 * the drawer prints that sentence rather than guessing at it.
 */
export interface ChecklistItem {
  key: string;
  label: string;
  required: boolean;
  done: boolean;
  /**
   * Who ticked it, as a USER ID - not a name. Null while it is
   * outstanding. Never print it raw: resolve it through the users the
   * module already loads (`nameOfUser`) and show nothing when it cannot
   * be resolved, because a uuid tells a reader nothing at all.
   */
  by: string | null;
  at: string | null;
  /**
   * Where the line came from: `type` is inherited from the request type's
   * standard list, `request` was added on this request. Absent on a
   * server that does not carry checklist editing yet.
   */
  source?: 'type' | 'request';
}

export interface WorkRequest {
  id: string;
  reference: string;
  project_id: string;
  project_code: string;
  project_name: string;
  client_name: string;
  department: string;
  /** The department's display name, resolved server-side. */
  department_name: string;
  /**
   * The FIRST of `request_types`, kept for everything that predates the
   * multi-type contract. Read `typeKeysOf(req)` rather than this.
   */
  request_type: string;
  /**
   * Every type the request is (SCADA *and* PLC programming *and* FDS).
   * Optional: a backend that predates it sends only `request_type`, and
   * `typeKeysOf` treats that as a list of one.
   */
  request_types?: string[];
  /** Their display names, in the same order. Server-resolved. */
  request_type_labels?: string[];
  /**
   * The de-duplicated UNION of the chosen types' fields - what the server
   * validates `fields` against, and therefore what the form must ask.
   * `fieldSpecsOf` falls back to the same union computed client-side.
   */
  field_specs?: RequestField[];
  title: string;
  description: string;
  status: Status;
  /** What this status may move to, per the server's own machine, now. */
  allowed_transitions: Status[];
  stage: string;
  /** The stage's display name, or null when the department dropped it. */
  stage_name: string | null;
  /** Moving to this stage completed the request. */
  stage_closes: boolean;
  stage_history: StageHistoryEntry[];
  raised_by_id: string;
  raised_by_name: string;
  assignees: Person[];
  responsible: Person | null;
  cost_centres: Record<string, string>;
  estimated_hours: Record<string, number>;
  quoted_hours: number | null;
  hours_logged: number;
  hours_to_complete: number | null;
  hours_at_completion: number | null;
  deviation_hours: number | null;
  /** Money as Decimal-as-TEXT (`"5220.00"`), NOT a number. See `fmtMoney`. */
  cost_at_completion: string | null;
  info_required_by: string | null;
  due_date: string | null;
  days_until_due: number | null;
  is_overdue: boolean;
  scheduled_start: string | null;
  scheduled_end: string | null;
  delivered_at: string | null;
  tested_at: string | null;
  priority: Priority;
  links: LinkRef[];
  fields: Record<string, unknown>;
  planner_uploaded: boolean;
  ball_in_court: BallInCourt;
  needs_info: string | null;
  depends_on: RelatedRequest[];
  blocks: RelatedRequest[];
  parent_id: string | null;
  parent_reference: string | null;
  children: RelatedRequest[];
  comment_count: number;
  attachments: Attachment[];
  created_at: string;
  updated_at: string;
  closed_at: string | null;

  /* ── Optional until the backend that serves them lands ───────── */

  /**
   * The department's sign-off list. Absent (not empty) on a server that
   * has no checklists: `checklistOf` treats both as "nothing to show",
   * and no screen may assume the array exists.
   */
  checklist?: ChecklistItem[];
  /** The server's own counts. `checklistProgress` falls back to counting. */
  checklist_done?: number;
  checklist_total?: number;
  /** A template is a shape to raise FROM; it is hidden from every list. */
  is_template?: boolean;
  /** The programme activity this request feeds, and its name if resolved. */
  schedule_activity_id?: string | null;
  schedule_activity_name?: string | null;
  /** The estimate positions it is booked against. */
  boq_position_ids?: string[];
  /** Their labels, in the same order, when the server resolves them. */
  boq_position_labels?: string[];
  /** Raise date + the department's `target_days`; past it, `is_late`. */
  target_date?: string | null;
  days_late?: number | null;
  is_late?: boolean;
}

export interface RequestFilters {
  project_id?: string;
  department?: string;
  /** Any-of: `?request_types=scada,plc` returns anything carrying either. */
  request_types?: string[];
  status?: Status | '';
  stage?: string;
  assignee_id?: string;
  raised_by?: string;
  q?: string;
  include_closed?: boolean;
  /**
   * Templates are hidden from every normal list; `true` asks for THEM and
   * nothing else. Undefined is the ordinary list, and is never sent.
   */
  is_template?: boolean;
  /** Only the ones past their target date. */
  late_only?: boolean;
  limit?: number;
  offset?: number;
}

export interface CreateRequestBody {
  project_id: string;
  department: string;
  /** The first of `request_types`; sent as well so an older server works. */
  request_type: string;
  /** Every type the request is. At least one; the order is kept. */
  request_types?: string[];
  title: string;
  description?: string;
  cost_centres?: Record<string, string>;
  estimated_hours?: Record<string, number>;
  quoted_hours?: number | null;
  info_required_by?: string | null;
  due_date?: string | null;
  priority?: Priority;
  links?: LinkRef[];
  fields?: Record<string, unknown>;
  assignee_ids?: string[];
  responsible_user_id?: string | null;
  depends_on_ids?: string[];
  parent_id?: string | null;
  draft?: boolean;
}

/** Any subset of a request that the server lets a client change. */
export type PatchRequestBody = Partial<
  Pick<
    WorkRequest,
    | 'title'
    | 'description'
    | 'status'
    | 'priority'
    | 'quoted_hours'
    | 'hours_to_complete'
    | 'info_required_by'
    | 'due_date'
    | 'scheduled_start'
    | 'scheduled_end'
    | 'delivered_at'
    | 'tested_at'
    | 'planner_uploaded'
    | 'links'
    | 'fields'
    | 'cost_centres'
    | 'estimated_hours'
  >
> & {
  depends_on_ids?: string[];
  parent_id?: string | null;
  request_types?: string[];
  /** Programme + estimate feeds; `null` / `[]` clears them. */
  schedule_activity_id?: string | null;
  boq_position_ids?: string[];
  /** Mark or unmark this request as a template to raise from. */
  is_template?: boolean;
};

/**
 * What one bulk write may change. Deliberately narrow: the fields the
 * list's action bar offers, and nothing a person could only mean one
 * request at a time (a title, a description, typed fields).
 */
export interface BulkPatch {
  assignee_ids?: string[];
  responsible_user_id?: string | null;
  stage?: string;
  due_date?: string | null;
  priority?: Priority;
  is_template?: boolean;
}

/**
 * `POST /requests/bulk` answers with BOTH halves: partial success is the
 * normal case (a stage that one request's department does not have, a
 * closing move blocked by an unticked required item), so the screen has
 * to report both rather than toasting a bare success.
 */
export interface BulkResult {
  updated: string[];
  refused: { id: string; reason: string }[];
}

export interface HandoffBody {
  department: string;
  /** The first of `request_types`; sent as well for an older server. */
  request_type: string;
  request_types?: string[];
  title?: string;
  description?: string;
  due_date?: string | null;
  info_required_by?: string | null;
  copy_links?: boolean;
}

export interface HoursEntry {
  id: string;
  user_id: string;
  user_name: string;
  date: string;
  hours: number;
  note: string | null;
}

export interface Comment {
  id: string;
  author_id: string;
  author_name: string;
  body: string;
  mention_ids: string[];
  created_at: string;
  kind: 'comment' | 'needs_info' | 'answer' | 'system';
}

export interface ActivityEntry {
  at: string;
  by_name: string;
  what: string;
  detail: string | null;
}

/* ── Planner ──────────────────────────────────────────────────────── */

export interface PlannerRow {
  request_id: string;
  reference: string;
  title: string;
  project_code: string;
  due_date: string | null;
  stage: string;
  assignees: Person[];
  /** ISO day → headcount. */
  alloc: Record<string, number>;
}

export interface Planner {
  days: string[];
  members: Person[];
  rows: PlannerRow[];
  capacity: Record<string, { available: number; allocated: number }>;
}

/* ── Summary / queue ──────────────────────────────────────────────── */

export interface DepartmentSummary {
  key: string;
  name: string;
  colour: string;
  open: number;
  overdue: number;
  with_requester: number;
  due_this_week: number;
  hours_quoted: number;
  hours_logged: number;
  /** Finished, waiting on the requester to close it. */
  awaiting_close: number;
  /**
   * Past the department's own target date. Optional: a server without the
   * lateness contract omits it, and the tab tooltip simply says nothing
   * about lateness rather than claiming zero.
   */
  late?: number;
}

export interface Summary {
  departments: DepartmentSummary[];
}

export interface MyQueue {
  assigned: WorkRequest[];
  responsible: WorkRequest[];
  raised: WorkRequest[];
  needs_my_answer: WorkRequest[];
}

/* ── ERP lookups the pickers need ─────────────────────────────────── */

export interface UserRow {
  id: string;
  email: string;
  full_name: string;
  role?: string;
  is_active?: boolean;
}

export interface ProjectRow {
  id: string;
  name: string;
  project_code: string | null;
  client_id: string | null;
}

/* ── The client ───────────────────────────────────────────────────── */

const BASE = '/v1/work-requests';

const enc = encodeURIComponent;

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}

/**
 * The department list. `include_inactive` asks for the retired request
 * types too - only the Manage screen wants them; every picker in the
 * module must offer the live ones.
 */
export async function fetchDepartments(includeInactive = false): Promise<Department[]> {
  const page = await apiGet<Page<Department>>(
    `${BASE}/departments${includeInactive ? '?include_inactive=true' : ''}`,
  );
  return page.items ?? [];
}

export function patchDepartment(key: string, patch: Partial<Department>): Promise<Department> {
  return apiPatch<Department, Partial<Department>>(`${BASE}/departments/${enc(key)}`, patch);
}

/* ── Request types, as the Manage screen edits them ───────────────── */

/** The key is minted from the label server-side; the new type comes back. */
export function createRequestType(deptKey: string, body: RequestTypeBody): Promise<RequestType> {
  return apiPost<RequestType, RequestTypeBody>(`${BASE}/departments/${enc(deptKey)}/request-types`, body);
}

export function patchRequestType(deptKey: string, typeKey: string, body: RequestTypeBody): Promise<RequestType> {
  return apiPatch<RequestType, RequestTypeBody>(
    `${BASE}/departments/${enc(deptKey)}/request-types/${enc(typeKey)}`,
    body,
  );
}

/**
 * Delete a type outright. The server REFUSES (409) when a request still
 * carries it and says so - the screen shows that sentence inline rather
 * than translating it, because "retire it instead" is the server's call.
 */
export function deleteRequestType(deptKey: string, typeKey: string): Promise<void> {
  return apiDelete<void>(`${BASE}/departments/${enc(deptKey)}/request-types/${enc(typeKey)}`);
}

/** The whole order in one write - `{keys: [...]}`, the new list back. */
export function reorderRequestTypes(deptKey: string, keys: string[]): Promise<RequestType[]> {
  return apiPut<RequestType[], { keys: string[] }>(`${BASE}/departments/${enc(deptKey)}/request-types/order`, { keys });
}

/**
 * The list's own query string, built ONCE.
 *
 * The export streams "the same filters as the list", which is only true
 * if both are spelled by the same code - a second hand-written copy is a
 * promise that drifts the first time a filter is added. `fetchRequests`
 * and `exportRequestsUrl` both come through here.
 */
export function requestQuery(filters: RequestFilters = {}, extra: Record<string, string | number | boolean | undefined> = {}): string {
  return qs({
    project_id: filters.project_id,
    department: filters.department,
    // Any-of, comma-joined. Empty means "no type filter" - never `?request_types=`.
    request_types: filters.request_types?.length ? filters.request_types.join(',') : undefined,
    status: filters.status,
    stage: filters.stage,
    assignee_id: filters.assignee_id,
    raised_by: filters.raised_by,
    q: filters.q,
    include_closed: filters.include_closed,
    // Only ever sent when asked for: `?is_template=false` on a server that
    // does not know the parameter is a filter nobody wanted.
    is_template: filters.is_template === undefined ? undefined : filters.is_template,
    late_only: filters.late_only ? true : undefined,
    ...extra,
  });
}

export async function fetchRequests(filters: RequestFilters = {}): Promise<WorkRequest[]> {
  const page = await apiGet<Page<WorkRequest>>(
    `${BASE}/requests${requestQuery(filters, { limit: filters.limit ?? 500, offset: filters.offset })}`,
  );
  return page.items ?? [];
}

/**
 * The templates: requests marked `is_template`, which the ordinary list
 * hides. Asked for by department so the raise dialog offers the ones that
 * belong to the department being raised against.
 */
export async function fetchTemplates(department?: string): Promise<WorkRequest[]> {
  const rows = (await apiGet<Page<WorkRequest>>(`${BASE}/requests${requestQuery({ department, is_template: true, include_closed: true }, { limit: 200 })}`)).items ?? [];
  // Filtered again here, and this is load-bearing: a backend that does not
  // know `?is_template=` yet answers with the ORDINARY list, which would
  // offer every open request in the department as a "template". Showing
  // none until the flag exists is the honest failure; showing all of them
  // is a picker that lies about what it is.
  return (rows ?? []).filter((r) => r.is_template === true);
}

export function createRequest(body: CreateRequestBody): Promise<WorkRequest> {
  return apiPost<WorkRequest, CreateRequestBody>(`${BASE}/requests`, body);
}

export function fetchRequest(id: string): Promise<WorkRequest> {
  return apiGet<WorkRequest>(`${BASE}/requests/${enc(id)}`);
}

export function patchRequest(id: string, patch: PatchRequestBody): Promise<WorkRequest> {
  return apiPatch<WorkRequest, PatchRequestBody>(`${BASE}/requests/${enc(id)}`, patch);
}

export function moveStage(id: string, stage: string, note?: string): Promise<WorkRequest> {
  return apiPost<WorkRequest, { stage: string; note?: string }>(
    `${BASE}/requests/${enc(id)}/stage`,
    note ? { stage, note } : { stage },
  );
}

/**
 * Tick or untick ONE checklist item. The whole request comes back, so the
 * progress line, the closing-stage gate and every list that shows the
 * request move together off one round trip.
 */
export function tickChecklist(id: string, key: string, done: boolean): Promise<WorkRequest> {
  return apiPost<WorkRequest, { key: string; done: boolean }>(`${BASE}/requests/${enc(id)}/checklist`, { key, done });
}

/* ── Editing the list itself ──────────────────────────────────────────
 *
 * A request's checklist starts as a copy of its TYPE's standard list and
 * can then be tailored on the request - a line the job needs that the
 * standard one does not, a wording the workshop actually uses. Every one
 * of these returns the WHOLE request, exactly like `tickChecklist`, so
 * the progress bar, the closing-stage gate and every list that shows the
 * request move together off one round trip.
 *
 * Who may: `work_requests.manage`, or the department's own lead. The
 * server is the authority and answers 403 with a sentence naming who can;
 * the screen only decides whether to OFFER an edit that would be refused.
 *
 * A server that does not carry these endpoints yet answers 404/405, which
 * `isModuleMissing` recognises - the section falls back to read-only
 * rather than showing controls that cannot work.
 */

export function addChecklistItem(
  id: string,
  body: { label: string; required?: boolean; after_key?: string | null },
): Promise<WorkRequest> {
  return apiPost<WorkRequest, typeof body>(`${BASE}/requests/${enc(id)}/checklist/items`, body);
}

export function patchChecklistItem(
  id: string,
  key: string,
  body: { label?: string; required?: boolean },
): Promise<WorkRequest> {
  return apiPatch<WorkRequest, typeof body>(`${BASE}/requests/${enc(id)}/checklist/items/${enc(key)}`, body);
}

/** Refused (409) for an item somebody has already ticked - that is a record. */
export function deleteChecklistItem(id: string, key: string): Promise<WorkRequest> {
  return apiDelete<WorkRequest>(`${BASE}/requests/${enc(id)}/checklist/items/${enc(key)}`);
}

export function reorderChecklist(id: string, keys: string[]): Promise<WorkRequest> {
  return apiPut<WorkRequest, { keys: string[] }>(`${BASE}/requests/${enc(id)}/checklist/order`, { keys });
}

/** Back to the standard list for this request's type. Destructive - confirm it. */
export function resetChecklist(id: string): Promise<WorkRequest> {
  return apiPost<WorkRequest, Record<string, never>>(`${BASE}/requests/${enc(id)}/checklist/reset`, {});
}

/**
 * Copy a request as a fresh DRAFT - the shape, the typed fields and the
 * hours estimate, none of the history, hours logged or conversation. The
 * new request comes back so the caller can open it.
 */
export function duplicateRequest(id: string, body: { title?: string; project_id?: string } = {}): Promise<WorkRequest> {
  return apiPost<WorkRequest, { title?: string; project_id?: string }>(`${BASE}/requests/${enc(id)}/duplicate`, body);
}

/**
 * One patch over many requests. Partial success is NORMAL - the server
 * applies what it can and lists what it would not, with a reason each -
 * so this never throws on a refusal; only a failed round trip throws.
 */
export function bulkPatch(ids: string[], patch: BulkPatch): Promise<BulkResult> {
  return apiPost<BulkResult, { ids: string[]; patch: BulkPatch }>(`${BASE}/requests/bulk`, { ids, patch });
}

/** The export endpoint for a set of filters - the SAME query as the list. */
export function exportRequestsUrl(filters: RequestFilters, format: 'csv' | 'xlsx'): string {
  return `${API_BASE}${BASE}/requests/export${requestQuery(filters, { format })}`;
}

/**
 * Download the export. Through `downloadWithAuth` rather than an `<a
 * href>`: the bearer token lives in the auth store, not in a cookie, so a
 * plain link fetches the file as an anonymous caller and gets a 401 -
 * which the browser renders as a downloaded error page, not as an error.
 */
export function exportRequests(filters: RequestFilters, format: 'csv' | 'xlsx'): Promise<void> {
  const stamp = new Date().toISOString().slice(0, 10);
  return downloadWithAuth(exportRequestsUrl(filters, format), `work-requests-${stamp}.${format}`);
}

/* ── The programme / estimate the request feeds ───────────────────── */

export interface FeedOption {
  id: string;
  label: string;
  sub?: string;
}

interface Page<T> {
  items?: T[];
}

/**
 * The project's schedule activities, flattened out of its schedules.
 *
 * There is no flat per-project activities endpoint, so the schedules are
 * listed and each one's activities fetched. The fan-out is capped and
 * every leg degrades to an empty list: a picker that shows five of six
 * schedules is usable, one that throws is not.
 */
export async function fetchScheduleActivities(projectId: string): Promise<FeedOption[]> {
  const page = await apiGet<Page<{ id: string; name: string }>>(`/v1/schedule/schedules/?project_id=${enc(projectId)}`);
  const schedules = (page?.items ?? []).slice(0, 5);
  const per = await Promise.all(
    schedules.map((s) =>
      apiGet<Page<{ id: string; name: string }>>(`/v1/schedule/schedules/${enc(s.id)}/activities/`)
        .then((p) => (p?.items ?? []).map((a) => ({ id: a.id, label: a.name || a.id, sub: schedules.length > 1 ? s.name : undefined })))
        .catch(() => [] as FeedOption[]),
    ),
  );
  return per.flat();
}

/** The project's BOQ positions, as "1.2.3 · Description" options. */
export async function fetchBoqPositions(projectId: string): Promise<FeedOption[]> {
  const boqs = await apiGet<{ id: string; name: string }[]>(`/v1/boq/boqs/?project_id=${enc(projectId)}`);
  const capped = (Array.isArray(boqs) ? boqs : []).slice(0, 3);
  const per = await Promise.all(
    capped.map((b) =>
      apiGet<{ positions?: { id: string; ordinal: string; description: string }[] }>(`/v1/boq/boqs/${enc(b.id)}`)
        .then((full) => (full?.positions ?? []).map((p) => ({ id: p.id, label: `${p.ordinal} ${p.description}`.trim(), sub: capped.length > 1 ? b.name : undefined })))
        .catch(() => [] as FeedOption[]),
    ),
  );
  return per.flat();
}

export function assignRequest(
  id: string,
  assignee_ids: string[],
  responsible_user_id?: string | null,
): Promise<WorkRequest> {
  return apiPost<WorkRequest, { assignee_ids: string[]; responsible_user_id?: string | null }>(
    `${BASE}/requests/${enc(id)}/assign`,
    responsible_user_id === undefined ? { assignee_ids } : { assignee_ids, responsible_user_id },
  );
}

export function askForInfo(id: string, question: string): Promise<WorkRequest> {
  return apiPost<WorkRequest, { question: string }>(`${BASE}/requests/${enc(id)}/needs-info`, { question });
}

export function answerInfo(id: string, answer: string): Promise<WorkRequest> {
  return apiPost<WorkRequest, { answer: string }>(`${BASE}/requests/${enc(id)}/answer`, { answer });
}

export function handoffRequest(id: string, body: HandoffBody): Promise<WorkRequest> {
  return apiPost<WorkRequest, HandoffBody>(`${BASE}/requests/${enc(id)}/handoff`, body);
}

export async function fetchHours(id: string): Promise<HoursEntry[]> {
  const page = await apiGet<Page<HoursEntry>>(`${BASE}/requests/${enc(id)}/hours`);
  return page.items ?? [];
}

/**
 * A logged entry AND the request it changed - one round trip, because
 * every total on the screen (logged, at completion, deviation, cost)
 * moves with it. NOT a bare row, and NOT the list.
 */
export type LoggedHours = HoursEntry & { request: WorkRequest };

export function logHours(
  id: string,
  entry: { date: string; hours: number; note?: string; user_id?: string },
): Promise<LoggedHours> {
  return apiPost<LoggedHours, typeof entry>(`${BASE}/requests/${enc(id)}/hours`, entry);
}

/**
 * `DELETE /requests/{id}/hours/{log_id}` - the entry id in the path, and
 * `204 No Content` back, so there is nothing to read. Callers refresh
 * through the shared invalidation.
 */
export function deleteHours(id: string, entryId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/requests/${enc(id)}/hours/${enc(entryId)}`);
}

/**
 * The conversation. The server hides `kind: 'system'` entries unless
 * asked - they are the audit trail, and the Activity section already
 * shows them, so the default is what a person actually wrote.
 */
export async function fetchComments(id: string, includeSystem = false): Promise<Comment[]> {
  const page = await apiGet<Page<Comment>>(
    `${BASE}/requests/${enc(id)}/comments${includeSystem ? '?include_system=true' : ''}`,
  );
  return page.items ?? [];
}

/** The one comment just posted - not the refreshed list. */
export function postComment(id: string, body: string, mention_ids: string[] = []): Promise<Comment> {
  return apiPost<Comment, { body: string; mention_ids: string[] }>(`${BASE}/requests/${enc(id)}/comments`, {
    body,
    mention_ids,
  });
}

export async function fetchActivity(id: string): Promise<ActivityEntry[]> {
  const page = await apiGet<Page<ActivityEntry>>(`${BASE}/requests/${enc(id)}/activity`);
  return page.items ?? [];
}

/** The stored file AND the request it now hangs from. */
export interface UploadedAttachment {
  attachment: Attachment;
  request: WorkRequest;
}

/** Multipart upload: the JSON helpers cannot send a file, so this is raw fetch. */
export async function uploadAttachment(id: string, file: File): Promise<UploadedAttachment> {
  const form = new FormData();
  form.append('file', file, file.name);
  const headers: Record<string, string> = { Accept: 'application/json' };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${BASE}/requests/${enc(id)}/attachments`, {
    method: 'POST',
    headers,
    body: form,
  });
  if (!res.ok) {
    let detail = `Upload failed (HTTP ${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return (await res.json()) as UploadedAttachment;
}

export function attachmentUrl(id: string, filename: string): string {
  return `${API_BASE}${BASE}/requests/${enc(id)}/attachments/${enc(filename)}`;
}

export function fetchPlanner(department: string, from: string, to: string): Promise<Planner> {
  return apiGet<Planner>(`${BASE}/planner${qs({ department, from, to })}`);
}

/** `{request_id, alloc}` - the row's saved allocation, not a whole row. */
export function putPlannerAlloc(
  requestId: string,
  alloc: Record<string, number>,
): Promise<{ request_id: string; alloc: Record<string, number> }> {
  return apiPut<{ request_id: string; alloc: Record<string, number> }, { alloc: Record<string, number> }>(
    `${BASE}/planner/${enc(requestId)}`,
    { alloc },
  );
}

/** `{department, capacity}` - the saved overrides, wrapped. */
export function putPlannerCapacity(
  department: string,
  capacity: Record<string, number>,
): Promise<{ department: string; capacity: Record<string, number> }> {
  return apiPut<{ department: string; capacity: Record<string, number> }, Record<string, number>>(
    `${BASE}/planner/capacity?department=${enc(department)}`,
    capacity,
  );
}

export function fetchSummary(projectId?: string | null): Promise<Summary> {
  return apiGet<Summary>(`${BASE}/summary${qs({ project_id: projectId ?? undefined })}`);
}

export function fetchMyQueue(): Promise<MyQueue> {
  return apiGet<MyQueue>(`${BASE}/my-queue`);
}

/**
 * Ring the due-tomorrow / overdue bells. A POST because it writes (each
 * reason fires once per request per day) and it takes NO body and no
 * `project_id` - it sweeps every job the caller can see.
 */
export function deadlineSweep(): Promise<{ published: number; detail: unknown[] }> {
  return apiPost<{ published: number; detail: unknown[] }, Record<string, never>>(`${BASE}/deadline-sweep`, {});
}

export function fetchUsers(): Promise<UserRow[]> {
  return apiGet<UserRow[]>('/v1/users/?limit=200');
}

export function fetchProjects(): Promise<ProjectRow[]> {
  return apiGet<ProjectRow[]>('/v1/projects/?limit=500');
}

export function fetchMe(): Promise<UserRow> {
  return apiGet<UserRow>('/v1/users/me/');
}
