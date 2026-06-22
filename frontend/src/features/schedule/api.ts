// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import {
  apiGet,
  apiPost,
  apiPatch,
  apiPut,
  apiDelete,
  API_BASE,
  getAuthToken,
} from '@/shared/lib/api';

export interface Schedule {
  id: string;
  project_id: string;
  name: string;
  description: string;
  start_date: string | null;
  end_date: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Activity {
  id: string;
  schedule_id: string;
  parent_id: string | null;
  name: string;
  description: string;
  wbs_code: string;
  start_date: string;
  end_date: string;
  duration_days: number;
  progress_pct: number;
  status: string;
  activity_type: string;
  dependencies: Array<{ activity_id: string; type: string; lag_days: number }>;
  resources: Array<{ name: string; type: string; allocation_pct: number }>;
  boq_position_ids: string[];
  /** BIM elements pinned to this activity for 4D scheduling.  Backend
   *  populates this from the `Activity.bim_element_ids` JSON column. */
  bim_element_ids?: string[] | null;
  color: string;
  sort_order: number;
  /** Activity metadata passthrough. BOQ-generated activities carry
   *  `duration_source` / `duration_method` = "estimated_fallback" here when
   *  the duration was estimated from unit-based production rates rather than
   *  real labor data. */
  metadata?: Record<string, unknown> | null;
}

export interface WorkOrder {
  id: string;
  activity_id: string;
  assembly_id: string | null;
  boq_position_id: string | null;
  code: string;
  description: string;
  assigned_to: string;
  planned_start: string | null;
  planned_end: string | null;
  actual_start: string | null;
  actual_end: string | null;
  planned_cost: number;
  actual_cost: number;
  status: string;
}

export interface GanttData {
  activities: Activity[];
  summary: {
    total_activities: number;
    completed: number;
    in_progress: number;
    delayed: number;
  };
}

export interface CPMActivityResult {
  activity_id: string;
  name: string;
  duration_days: number;
  early_start: number;
  early_finish: number;
  late_start: number;
  late_finish: number;
  total_float: number;
  is_critical: boolean;
}

export interface CriticalPathResponse {
  schedule_id: string;
  project_duration_days: number;
  critical_path: CPMActivityResult[];
  all_activities: CPMActivityResult[];
}

export interface RiskAnalysisResponse {
  schedule_id: string;
  deterministic_days: number;
  p50_days: number;
  p80_days: number;
  p95_days: number;
  mean_days: number;
  std_dev_days: number;
  risk_buffer_days: number;
  activity_risks: Array<{
    activity_id: string;
    name: string;
    duration_days: number;
    optimistic: number;
    most_likely: number;
    pessimistic: number;
    expected: number;
    std_dev: number;
    is_critical: boolean;
  }>;
}

/**
 * Scalar earned-value (EVM) metrics for a schedule at a data date.
 *
 * Mirrors the backend ``EvmSummaryResponse``. Money fields arrive as the
 * platform Decimal-as-string wire contract (decode via `shared/lib/money.ts`);
 * the dimensionless indices and the CPI-method forecast are `number | null`
 * (`null` when the schedule is not cost-loaded or a denominator is zero).
 */
export interface EvmSummary {
  schedule_id: string;
  as_of_date: string;
  /** Planned value (BCWS), time-phased to the data date. Decimal string. */
  planned_value: string;
  /** Earned value (BCWP). Decimal string. */
  earned_value: string;
  /** Actual cost (ACWP). Decimal string. */
  actual_cost: string;
  /** Budget at completion (Σ planned cost). Decimal string. */
  budget_at_completion: string;
  /** Schedule variance = EV - PV. Decimal string. */
  schedule_variance: string;
  /** Cost variance = EV - AC. Decimal string. */
  cost_variance: string;
  /** Estimate at completion = BAC / CPI. Decimal string or null. */
  estimate_at_completion: string | null;
  /** Estimate to complete = EAC - AC. Decimal string or null. */
  estimate_to_complete: string | null;
  /** Variance at completion = BAC - EAC. Decimal string or null. */
  variance_at_completion: string | null;
  /** Schedule performance index = EV / PV. */
  spi: number | null;
  /** Cost performance index = EV / AC. */
  cpi: number | null;
  has_cost_data: boolean;
}

/**
 * 4D snapshot: per-BIM-element status on a given as-of date. ``elements`` maps
 * each resolved element id to its derived status
 * (not_started / in_progress / completed / delayed / ahead_of_schedule).
 */
export interface ScheduleSnapshot {
  schedule_id: string;
  as_of_date: string;
  model_version_id: string | null;
  elements: Record<string, string>;
}

/* ── Baselines ─────────────────────────────────────────────────────────── */

/**
 * A schedule baseline snapshot. ``snapshot_data`` is the frozen activity set
 * captured at ``baseline_date``; the diff engine consumes it as the base side
 * of a comparison. Mirrors the backend ``BaselineResponse`` (schedule module).
 */
export interface ScheduleBaseline {
  id: string;
  schedule_id: string | null;
  project_id: string;
  name: string;
  baseline_date: string;
  snapshot_data: Record<string, unknown>;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

/* ── Schedule comparison / diff (T1.3) ─────────────────────────────────────
 *
 * Compares two snapshots of a schedule (a captured baseline, or an inline
 * envelope, against the live schedule or another baseline) and returns a
 * categorized diff plus roll-up metrics. Mirrors the backend schemas
 * SnapshotEnvelopeResponse / ScheduleDiffRequest / ScheduleDiffResponse.
 */

export interface SnapshotEnvelope {
  schedule_id: string;
  envelope: Record<string, unknown>;
}

export interface ScheduleDiffRequestBody {
  base_baseline_id?: string | null;
  base_envelope?: Record<string, unknown> | null;
  target_baseline_id?: string | null;
}

/**
 * Per-field change map: field name -> a small object describing the before/after
 * values. The inner shape is engine-defined (e.g. ``{from, to}``); the UI only
 * needs the field names, so the inner value is left opaque.
 */
export type DiffFieldChange = Record<string, Record<string, unknown>>;

export interface DiffActivityChange {
  key: string;
  /** "added" | "removed" | "modified" */
  change_type: string;
  categories: string[];
  fields: DiffFieldChange;
  finish_movement_days: number;
  critical_path: boolean;
  name: string | null;
  wbs_code: string | null;
}

export interface DiffRelationshipChange {
  /** [predecessor_key, successor_key] */
  key: string[];
  /** "added" | "removed" | "retyped" | "relagged" */
  change_type: string;
  categories: string[];
  fields: DiffFieldChange;
}

export interface DiffCalendarChange {
  key: string;
  /** "added" | "removed" | "modified" */
  change_type: string;
  categories: string[];
}

export interface DiffSummary {
  net_finish_movement_days: number;
  count_by_category: Record<string, number>;
  activities_added: number;
  activities_removed: number;
  activities_changed: number;
  relationships_added: number;
  relationships_removed: number;
  relationships_retyped: number;
  relationships_relagged: number;
  critical_path_in: number;
  critical_path_out: number;
  /** Decimal-as-string money delta. */
  cost_planned_delta: string;
  /** Decimal-as-string money delta. */
  cost_actual_delta: string;
  largest_slips: Array<Record<string, unknown>>;
}

export interface ScheduleDiff {
  schedule_id: string;
  base_label: string;
  target_label: string;
  activities: DiffActivityChange[];
  relationships: DiffRelationshipChange[];
  calendars: DiffCalendarChange[];
  summary: DiffSummary;
}

/* ── Schedule interchange (T1.1) ────────────────────────────────────────────
 *
 * Lossless export / import of a schedule in the canonical interchange JSON
 * (``{format, format_version, schedule, activities, relationships}``), plus a
 * read-only DCMA-style hygiene dry-run ("clean preview") and a normalise-on-
 * import option. Mirrors the backend interchange schemas. The interchange
 * document is engine-defined, so it is treated as an opaque record on the wire.
 */

/** The canonical interchange JSON envelope (opaque to the UI). */
export type InterchangeDocument = Record<string, unknown>;

/**
 * One hygiene action the cleaner would (or did) apply. ``code`` is a stable
 * machine key (e.g. ``drop_dangling_relationship``), ``target`` names the
 * affected entity and ``detail`` is a human-readable description.
 */
export interface CleanAction {
  code: string;
  target: string;
  detail: string;
}

/**
 * Read-only DCMA-style hygiene dry-run for a schedule. ``actions`` is the list
 * of repairs that *would* apply; ``stats`` carries the counts (activities,
 * relationships, lead_count, hard_constraint_count, the missing-logic tallies,
 * and the per-repair would-fix counts). Nothing is mutated.
 */
export interface ScheduleCleanPreview {
  schedule_id: string;
  actions: CleanAction[];
  stats: Record<string, number>;
}

/** Lossless export of a schedule as the interchange document. */
export interface ScheduleExport {
  schedule_id: string;
  document: InterchangeDocument;
}

/** Request body for importing an interchange document into a project. */
export interface ScheduleImportBody {
  project_id: string;
  document: InterchangeDocument;
  /** Normalise (DCMA-clean) the schedule on import. Defaults to true server-side. */
  clean?: boolean;
  /** Override the imported schedule's name (null / omitted keeps the document's). */
  name_override?: string | null;
}

/**
 * Result of an import. Returns the new schedule id, the created counts, the
 * hygiene actions actually applied (when ``clean``), the stats, and a
 * ``ref_map`` from the document's source activity refs to the new ids.
 */
export interface ScheduleImportResult {
  schedule_id: string;
  activity_count: number;
  relationship_count: number;
  clean_actions: CleanAction[];
  stats: Record<string, number>;
  ref_map: Record<string, string>;
}

/* ── Progress rigor (T3.2) ─────────────────────────────────────────────────
 *
 * Typed percent-complete (duration/units/physical), weighted steps, suspend/
 * resume, per-activity calendar, and time-phased planned value. Mirrors the
 * backend progress_schemas.py. Money / quantity values are Decimal-as-string.
 */

export type PercentCompleteType = 'physical' | 'duration' | 'units';

/** Deterministic EVM-distortion warning keys returned by the backend. */
export type EvmWarningKey =
  | 'units_type_without_budgeted_units'
  | 'duration_type_on_nonlinear_cost'
  | 'physical_manual_pct_is_subjective'
  | 'all_steps_zero_weight';

export interface TypedActivityView {
  id: string;
  schedule_id: string;
  name: string;
  progress_pct: string | null;
  percent_complete_type: PercentCompleteType;
  remaining_duration: number | null;
  budgeted_units: string | null;
  installed_units: string | null;
  calendar_id: string | null;
  status: string;
  suspended_at: string | null;
  resumed_at: string | null;
  suspend_reason: string | null;
  start_date: string | null;
  end_date: string | null;
  forecast_finish?: string | null;
}

export interface TypedProgressResponse {
  activity: TypedActivityView;
  evm_warnings: EvmWarningKey[];
  forecast_finish: string | null;
  remaining_duration: number | null;
}

export interface PercentTypePreviewResponse {
  percent_complete_type: PercentCompleteType;
  evm_warnings: EvmWarningKey[];
}

export interface SuspendResumeResponse {
  activity: TypedActivityView;
  forecast_finish: string | null;
}

export interface ActivityStep {
  id: string;
  activity_id: string;
  name: string;
  /** Decimal-as-string weight (>= 0). */
  weight: string;
  /** Decimal-as-string percent (0..100). */
  percent_complete: string;
  is_milestone: boolean;
  sort_order: number;
}

export interface PlannedValuePreview {
  as_of: string;
  /** Decimal-as-string time-phased PV. */
  planned_value: string;
  /** Decimal-as-string BAC (Σ planned cost). */
  budget_at_completion: string;
}

export interface EvmSnapshotSummary {
  snapshot_date: string;
  bac: string;
  pv: string;
  ev: string;
  ac: string;
  sv: string;
  cv: string;
  spi: string;
  cpi: string;
}

export interface DataDateAdvanceResponse {
  schedule_id: string;
  data_date: string;
  snapshot: EvmSnapshotSummary;
}

export interface TypedProgressBody {
  type?: PercentCompleteType;
  percent?: number;
  installed_units?: number;
  budgeted_units?: number;
  remaining_duration?: number;
  data_date?: string;
}

/* ── T2.3 codes / UDFs / layouts ────────────────────────────────────────────
 *
 * Activity code dictionaries (hierarchical values), user-defined fields (UDFs)
 * and saved grid layouts, plus the server-side grouped / filtered / paged
 * activity grid. Mirrors backend codes_schemas.py. A layout group-by/column key
 * is a small namespaced grammar: a bare static column name, ``code:<uuid>`` or
 * ``udf:<uuid>``; in this UI we only build ``code:<uuid>`` group-by keys (always
 * valid), since static columns are whitelist-gated server-side.
 *
 * Band/path semantics (from codes_bandtree.py): an unassigned activity falls
 * into a ``(none)`` band whose key is the sentinel ``__none__``. Each band
 * carries a ``path`` (its keys from the root down); each row carries a
 * ``group_path`` of the same level keys. A row sits under a band when the band's
 * ``path`` is a prefix of the row's ``group_path``. The expand/collapse
 * identifier we track is that ``path`` joined by NUL.
 */

/* ── T3.4 realtime collaboration ────────────────────────────────────────────
 *
 * Presence snapshot of who is editing a schedule, plus an optimistic-concurrency
 * guarded activity update keyed off a client-held base revision. Mirrors the
 * backend realtime_schemas.py. Routes are mounted under the same
 * ``/v1/schedule`` prefix as the core schedule router:
 *   GET   /v1/schedule/schedules/{id}/presence/
 *   GET   /v1/schedule/activities/{id}/revision/
 *   PATCH /v1/schedule/activities/{id}/guarded/   (409 stale / 422 invalid)
 *
 * The guarded PATCH returns the up-to-date activity + its new revision on apply
 * or no-op; HTTP 409 carries the authoritative revision + current state so the
 * client can rebase; HTTP 422 means a malformed base revision or a field outside
 * the editable allowlist. Both non-2xx codes surface as an ``ApiError`` from the
 * shared client (branch on ``err.status``); the 409 body is ``RevisionConflict``.
 */

/** One connected co-editor in a schedule presence room. */
export interface SchedulePresenceUser {
  user_id: string;
  user_name: string;
}

/** REST snapshot of who is currently connected to a schedule room. */
export interface SchedulePresence {
  schedule_id: string;
  users: SchedulePresenceUser[];
}

/** The current optimistic-concurrency revision of an activity. */
export interface ActivityRevision {
  activity_id: string;
  revision: number;
}

/** Result of an applied (or no-op) guarded update: the activity + its revision. */
export interface GuardedUpdateResult {
  activity: Record<string, unknown>;
  revision: number;
}

/**
 * Body of the HTTP 409 returned when the client's base revision is stale. Read
 * off ``ApiError.body`` when the guarded PATCH rejects with status 409.
 */
export interface RevisionConflict {
  detail: string;
  current_revision: number;
  current_state: Record<string, unknown>;
}

/** Editable fields a guarded activity update may carry (allowlist is enforced server-side). */
export interface GuardedUpdateFields {
  progress_pct?: number;
  status?: string;
  name?: string;
  [key: string]: unknown;
}

/* ── T2.3 codes / UDFs / layouts (continued) ───────────────────────────────── */

/** Sentinel key the backend uses for an unassigned ``(none)`` band/path level. */
export const GROUP_NONE_KEY = '__none__';

export interface CodeDictionary {
  id: string;
  project_id: string | null;
  is_library: boolean;
  name: string;
  description: string;
  color_band: boolean;
  sort_order: number;
}

export interface CodeDictionaryCreateBody {
  name: string;
  description?: string;
  color_band?: boolean;
  sort_order?: number;
}

export interface CodeValue {
  id: string;
  dictionary_id: string;
  parent_id: string | null;
  code: string;
  label: string;
  color: string;
  depth: number;
  sort_order: number;
}

export interface CodeValueCreateBody {
  code: string;
  label?: string;
  color?: string;
  parent_id?: string | null;
  sort_order?: number;
}

export type UdfValueType = 'text' | 'number' | 'date' | 'bool' | 'enum';

export interface ScheduleUdf {
  id: string;
  project_id: string;
  key: string;
  label: string;
  value_type: UdfValueType;
  enum_values: string[];
  sort_order: number;
}

export interface UdfCreateBody {
  key: string;
  label?: string;
  value_type?: UdfValueType;
  enum_values?: string[];
  sort_order?: number;
}

/** A code chip on a grouped row (dictionary value resolved to code + label). */
export interface CodeAssignment {
  dictionary_id: string;
  value_id: string;
  code: string;
  label: string;
}

/** A UDF value on a grouped row. ``value`` is typed per the UDF's value_type. */
export interface UdfValueRead {
  udf_id: string;
  value_type: UdfValueType;
  value: unknown;
}

/** One group-by level in a layout spec. ``key`` is ``code:<dictionary_id>``. */
export interface LayoutGroupBy {
  key: string;
  color_band: boolean;
}

/**
 * The saved-layout spec. ``extra='forbid'`` server-side, so only the documented
 * fields may be sent. v1 of this UI drives ``group_by`` + ``timescale`` and
 * leaves the richer fields at their server defaults (sent as empty / defaults).
 */
export interface LayoutSpec {
  columns: Array<{ key: string; width?: number | null }>;
  group_by: LayoutGroupBy[];
  sort: Array<{ field: string; direction?: 'asc' | 'desc' }>;
  filter: Record<string, unknown>;
  code_filter: Array<{ dictionary_id: string; value_ids: string[] }>;
  udf_filter: Array<{ udf_id: string; op?: string; value?: unknown }>;
  timescale: 'day' | 'week' | 'month' | 'quarter' | 'year';
  bar_style: { by?: string; show_critical?: boolean; show_baseline?: boolean };
}

export type LayoutShareScope = 'private' | 'project' | 'workspace';

export interface ScheduleLayout {
  id: string;
  owner_id: string;
  schedule_id: string;
  project_id: string | null;
  name: string;
  share_scope: LayoutShareScope;
  is_default: boolean;
  spec: Record<string, unknown>;
}

export interface LayoutCreateBody {
  name: string;
  share_scope?: LayoutShareScope;
  is_default?: boolean;
  spec?: Partial<LayoutSpec>;
}

/** A banded group header in the grouped grid (depth-first, counts sum to total). */
export interface GroupBand {
  key: string;
  label: string;
  color: string;
  depth: number;
  count: number;
  path: string[];
}

/** A leaf activity row in the grouped grid. */
export interface GroupedRow {
  id: string;
  name: string;
  wbs_code: string;
  start_date: string | null;
  end_date: string | null;
  duration_days: number;
  progress_pct: number;
  status: string;
  total_float: number | null;
  is_critical: boolean;
  group_path: string[];
  codes: CodeAssignment[];
  udf_values: UdfValueRead[];
}

export interface GroupedResponse {
  groups: GroupBand[];
  rows: GroupedRow[];
  page: number;
  page_size: number;
  total_estimate: number;
}

export interface GroupedRequestBody {
  spec?: Partial<LayoutSpec>;
  layout_id?: string;
  page?: number;
  page_size?: number;
  expanded_groups?: string[];
}

/**
 * Build a full LayoutSpec from the (sparse) builder state, filling every field
 * the server's ``extra='forbid'`` spec expects with its documented default.
 * Only ``code:<uuid>`` group-by keys are produced here.
 */
export function buildLayoutSpec(
  groupBy: LayoutGroupBy[],
  timescale: LayoutSpec['timescale'] = 'week',
): LayoutSpec {
  return {
    columns: [],
    group_by: groupBy,
    sort: [],
    filter: {},
    code_filter: [],
    udf_filter: [],
    timescale,
    bar_style: { by: 'status', show_critical: true, show_baseline: false },
  };
}

/** Defensive unwrap: handle both plain array and paginated {items, total} responses. */
function unwrapList<T>(res: T[] | { items: T[] }): T[] {
  return Array.isArray(res) ? res : res.items ?? [];
}

/* ── Vendor interchange: MS Project XML + XER (#205) ─────────────────────
   These file routes live on the schedule module router whose decorators are
   prefixed with ``/schedule`` while the module itself mounts at
   ``/api/v1/schedule`` - hence the doubled segment below. Imports are
   multipart POSTs into an existing schedule; exports stream a file we
   download client-side with the bearer token attached (a plain link would
   not carry the Authorization header). */

const SCHEDULE_FILE_BASE = `${API_BASE}/v1/schedule/schedule`;

/** Result of importing a vendor file into a schedule. */
export interface VendorImportResult {
  activities_imported: number;
  relationships_imported: number;
  calendars_imported: number;
  warnings: string[];
}

function scheduleFileHeaders(json: boolean): HeadersInit {
  const headers: Record<string, string> = { 'X-DDC-Client': 'OE/1.0' };
  if (json) headers['Accept'] = 'application/json';
  const token = getAuthToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

async function readErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') return body.detail;
  } catch {
    /* not JSON */
  }
  return fallback;
}

async function uploadScheduleFile(
  kind: 'msp-xml' | 'xer',
  scheduleId: string,
  file: File,
): Promise<VendorImportResult> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(
    `${SCHEDULE_FILE_BASE}/import/${kind}/?schedule_id=${encodeURIComponent(scheduleId)}`,
    { method: 'POST', headers: scheduleFileHeaders(true), body: form },
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, `Import failed (${res.status})`));
  }
  return res.json() as Promise<VendorImportResult>;
}

async function downloadScheduleExport(
  kind: 'msp-xml' | 'csv',
  scheduleId: string,
  filename: string,
): Promise<void> {
  const res = await fetch(
    `${SCHEDULE_FILE_BASE}/export/${kind}/?schedule_id=${encodeURIComponent(scheduleId)}`,
    { method: 'GET', headers: scheduleFileHeaders(false) },
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, `Export failed (${res.status})`));
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    a.remove();
    URL.revokeObjectURL(url);
  }, 1000);
}

export const scheduleApi = {
  // Schedules
  listSchedules: (projectId: string) =>
    apiGet<Schedule[] | { items: Schedule[] }>(`/v1/schedule/schedules/?project_id=${projectId}`).then(unwrapList),
  getSchedule: (id: string) => apiGet<Schedule>(`/v1/schedule/schedules/${id}`),
  createSchedule: (data: { project_id: string; name: string; description?: string; start_date?: string; end_date?: string }) =>
    apiPost<Schedule>('/v1/schedule/schedules/', data),
  updateSchedule: (id: string, data: { name?: string; description?: string; start_date?: string; end_date?: string; status?: string }) =>
    apiPatch<Schedule>(`/v1/schedule/schedules/${id}`, data),

  // Activities
  getGantt: (scheduleId: string) =>
    apiGet<GanttData>(`/v1/schedule/schedules/${scheduleId}/gantt/`),
  createActivity: (scheduleId: string, data: Partial<Activity>) =>
    apiPost<Activity>(`/v1/schedule/schedules/${scheduleId}/activities/`, data),
  updateActivity: (activityId: string, data: Partial<Activity>) =>
    apiPatch<Activity>(`/v1/schedule/activities/${activityId}`, data),
  deleteActivity: (activityId: string) =>
    apiDelete(`/v1/schedule/activities/${activityId}`),
  clearActivities: (scheduleId: string) =>
    apiDelete<{ schedule_id: string; deleted: number }>(
      `/v1/schedule/schedules/${scheduleId}/activities/`,
    ),
  linkPosition: (activityId: string, positionId: string) =>
    apiPost(`/v1/schedule/activities/${activityId}/link-position/`, { boq_position_id: positionId }),
  /** Structural reorder/re-parent of a schedule's activities. ``items`` is the
   *  full desired top-to-bottom order with each row's new parent (null = root).
   *  Dates and dependencies are untouched. */
  reorderActivities: (
    scheduleId: string,
    items: Array<{ id: string; parentId: string | null }>,
  ) =>
    apiPost<Activity[]>(`/v1/schedule/schedules/${scheduleId}/activities/reorder/`, {
      items: items.map((it) => ({ id: it.id, parent_id: it.parentId })),
    }),
  updateProgress: (activityId: string, progressPct: number) =>
    apiPatch(`/v1/schedule/activities/${activityId}/progress/`, { progress_pct: progressPct }),

  // CPM & BOQ Generation
  generateFromBOQ: (
    scheduleId: string,
    boqId: string,
    totalProjectDays?: number,
    /** Optional subset of BOQ position ids to include. Omit to generate the
     *  whole BOQ. The backend adds the ancestors needed to host any selected
     *  leaf, so passing only the desired leaf (work) positions is enough. */
    positionIds?: string[],
  ) =>
    apiPost<Activity[]>(`/v1/schedule/schedules/${scheduleId}/generate-from-boq/`, {
      boq_id: boqId,
      ...(totalProjectDays != null ? { total_project_days: totalProjectDays } : {}),
      ...(positionIds != null ? { position_ids: positionIds } : {}),
    }),
  calculateCPM: (scheduleId: string) =>
    apiPost<CriticalPathResponse>(`/v1/schedule/schedules/${scheduleId}/calculate-cpm/`),
  getRiskAnalysis: (scheduleId: string) =>
    apiGet<RiskAnalysisResponse>(`/v1/schedule/schedules/${scheduleId}/risk-analysis/`),

  // EVM (earned value) + 4D snapshot
  /** Scalar EVM rollup (PV/EV/AC, SPI/CPI, EAC) for a schedule at a data date. */
  getEvmSummary: (scheduleId: string, asOfDate?: string) =>
    apiGet<EvmSummary>(
      `/v1/schedule/schedules/${scheduleId}/evm-summary/${
        asOfDate ? `?as_of_date=${encodeURIComponent(asOfDate)}` : ''
      }`,
    ),
  /** 4D element-status snapshot for a schedule at a data date (v2 surface). */
  getSnapshot: (scheduleId: string, params?: { asOfDate?: string; modelVersionId?: string }) => {
    const qs = new URLSearchParams();
    if (params?.asOfDate) qs.set('as_of_date', params.asOfDate);
    if (params?.modelVersionId) qs.set('model_version_id', params.modelVersionId);
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return apiGet<ScheduleSnapshot>(`/v2/schedules/${scheduleId}/snapshot${suffix}`);
  },

  // Work Orders
  // The backend /work-orders/ endpoint requires schedule_id and has no
  // activity_id filter, so schedule_id is mandatory here to avoid a 422.
  listWorkOrders: (params: { schedule_id: string }) =>
    apiGet<WorkOrder[] | { items: WorkOrder[] }>(`/v1/schedule/work-orders/?${new URLSearchParams(params as Record<string, string>)}`).then(unwrapList),
  createWorkOrder: (activityId: string, data: Partial<WorkOrder>) =>
    apiPost<WorkOrder>(`/v1/schedule/activities/${activityId}/work-orders/`, data),
  updateWorkOrder: (id: string, data: Partial<WorkOrder>) =>
    apiPatch<WorkOrder>(`/v1/schedule/work-orders/${id}`, data),

  // Baselines (project-scoped). Used as the base side of a schedule diff.
  listBaselines: (projectId: string) =>
    apiGet<ScheduleBaseline[] | { items: ScheduleBaseline[] }>(
      `/v1/schedule/baselines/?project_id=${encodeURIComponent(projectId)}`,
    ).then(unwrapList),

  // Schedule comparison / diff (T1.3)
  /** Flatten the live schedule into the canonical diff envelope (e.g. to store as a baseline). */
  getSnapshotEnvelope: (scheduleId: string) =>
    apiGet<SnapshotEnvelope>(
      `/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/snapshot-envelope`,
    ),
  /**
   * Categorized diff between a base and a target snapshot of this schedule.
   * Base is a captured baseline (``base_baseline_id``) or an inline envelope
   * (``base_envelope``); target defaults to the live schedule, or another
   * baseline via ``target_baseline_id``.
   */
  diffSchedule: (scheduleId: string, body: ScheduleDiffRequestBody) =>
    apiPost<ScheduleDiff, ScheduleDiffRequestBody>(
      `/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/diff`,
      body,
    ),

  /* ── Schedule interchange (T1.1) ────────────────────────────────────── */

  /** Lossless export of a schedule as the canonical interchange document. */
  exportSchedule: (scheduleId: string) =>
    apiGet<ScheduleExport>(
      `/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/export`,
    ),
  /** Read-only DCMA-style hygiene dry-run for a schedule (mutates nothing). */
  cleanPreviewSchedule: (scheduleId: string) =>
    apiGet<ScheduleCleanPreview>(
      `/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/clean-preview`,
    ),
  /** Import an interchange document into a project (optionally normalising it). */
  importSchedule: (body: ScheduleImportBody) =>
    apiPost<ScheduleImportResult, ScheduleImportBody>(
      `/v1/schedule/schedules/import`,
      body,
    ),

  /* ── MS Project / XER files (#205) ───────────────────────────────────── */

  /** Import a Microsoft Project XML file into an existing schedule. */
  importMspXml: (scheduleId: string, file: File) =>
    uploadScheduleFile('msp-xml', scheduleId, file),
  /** Import an XER schedule file into an existing schedule. */
  importXer: (scheduleId: string, file: File) =>
    uploadScheduleFile('xer', scheduleId, file),
  /** Download a schedule as a Microsoft Project XML (MSPDI) file. */
  exportMspXml: (scheduleId: string, filename: string) =>
    downloadScheduleExport('msp-xml', scheduleId, filename),
  /** Download a schedule as a CSV file. */
  exportCsv: (scheduleId: string, filename: string) =>
    downloadScheduleExport('csv', scheduleId, filename),

  /* ── Progress rigor (T3.2) ──────────────────────────────────────────── */

  /** Set typed progress (duration/units/physical) on an activity. */
  updateProgressTyped: (activityId: string, body: TypedProgressBody) =>
    apiPatch<TypedProgressResponse, TypedProgressBody>(
      `/v1/schedule/activities/${encodeURIComponent(activityId)}/typed-progress/`,
      body,
    ),
  /** Preview the EVM-distortion warnings a percent-type change would raise. */
  previewPercentType: (activityId: string, type: PercentCompleteType) =>
    apiPost<PercentTypePreviewResponse, { type: PercentCompleteType }>(
      `/v1/schedule/activities/${encodeURIComponent(activityId)}/percent-type/preview/`,
      { type },
    ),
  /** Commit a percent-complete type change and recompute the activity. */
  setPercentType: (activityId: string, type: PercentCompleteType) =>
    apiPut<TypedProgressResponse, { type: PercentCompleteType }>(
      `/v1/schedule/activities/${encodeURIComponent(activityId)}/percent-type/`,
      { type },
    ),
  /** Set (calendarId) or clear (null) an activity's per-activity calendar. */
  setActivityCalendar: (activityId: string, calendarId: string | null) =>
    apiPut<TypedProgressResponse, { calendar_id: string | null }>(
      `/v1/schedule/activities/${encodeURIComponent(activityId)}/calendar/`,
      { calendar_id: calendarId },
    ),
  /** Suspend an in_progress / not_started activity (freezes remaining duration). */
  suspendActivity: (activityId: string, reason: string, effectiveDate?: string) =>
    apiPost<SuspendResumeResponse, { reason: string; effective_date?: string }>(
      `/v1/schedule/activities/${encodeURIComponent(activityId)}/suspend/`,
      { reason, ...(effectiveDate ? { effective_date: effectiveDate } : {}) },
    ),
  /** Resume a suspended activity (reschedules from the frozen remaining duration). */
  resumeActivity: (activityId: string, effectiveDate?: string) =>
    apiPost<SuspendResumeResponse, { effective_date?: string }>(
      `/v1/schedule/activities/${encodeURIComponent(activityId)}/resume/`,
      effectiveDate ? { effective_date: effectiveDate } : {},
    ),
  /** List an activity's weighted progress steps. */
  listSteps: (activityId: string) =>
    apiGet<ActivityStep[]>(`/v1/schedule/activities/${encodeURIComponent(activityId)}/steps/`),
  /** Add a weighted progress step to an activity. */
  createStep: (
    activityId: string,
    data: { name?: string; weight?: number; percent_complete?: number; is_milestone?: boolean; sort_order?: number },
  ) =>
    apiPost<ActivityStep, typeof data>(
      `/v1/schedule/activities/${encodeURIComponent(activityId)}/steps/`,
      data,
    ),
  /** Edit a weighted progress step (recomputes the parent activity). */
  updateStep: (
    stepId: string,
    data: { name?: string; weight?: number; percent_complete?: number; is_milestone?: boolean; sort_order?: number },
  ) => apiPatch<ActivityStep, typeof data>(`/v1/schedule/steps/${encodeURIComponent(stepId)}/`, data),
  /** Delete a weighted progress step (recomputes the parent activity). */
  deleteStep: (stepId: string) => apiDelete(`/v1/schedule/steps/${encodeURIComponent(stepId)}/`),
  /** Time-phased planned value (PV) preview at a date (read-only, no snapshot). */
  getPlannedValue: (scheduleId: string, asOf: string) =>
    apiGet<PlannedValuePreview>(
      `/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/planned-value/?as_of=${encodeURIComponent(asOf)}`,
    ),
  /** Advance the data date; refreshes the time-phased PV/EV snapshot. */
  advanceDataDate: (scheduleId: string, dataDate: string) =>
    apiPut<DataDateAdvanceResponse, { data_date: string }>(
      `/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/data-date/`,
      { data_date: dataDate },
    ),

  /* ── T2.3 codes / UDFs / layouts ────────────────────────────────────── */

  // Code dictionaries
  /** List the project's code dictionaries. */
  listCodeDictionaries: (projectId: string) =>
    apiGet<CodeDictionary[]>(`/v1/schedule/projects/${encodeURIComponent(projectId)}/code-dictionaries/`),
  /** Create a code dictionary in the project. */
  createCodeDictionary: (projectId: string, body: CodeDictionaryCreateBody) =>
    apiPost<CodeDictionary, CodeDictionaryCreateBody>(
      `/v1/schedule/projects/${encodeURIComponent(projectId)}/code-dictionaries/`,
      body,
    ),
  /** Delete a (project) code dictionary. */
  deleteCodeDictionary: (dictId: string) =>
    apiDelete(`/v1/schedule/code-dictionaries/${encodeURIComponent(dictId)}`),
  /** List the workspace library dictionary templates available to import. */
  listLibraryDictionaries: () =>
    apiGet<CodeDictionary[]>(`/v1/schedule/code-dictionaries/library/`),
  /** Import a library dictionary template into the project. */
  importLibraryDictionary: (projectId: string, libraryDictionaryId: string) =>
    apiPost<CodeDictionary, { library_dictionary_id: string }>(
      `/v1/schedule/projects/${encodeURIComponent(projectId)}/code-dictionaries/import-library`,
      { library_dictionary_id: libraryDictionaryId },
    ),

  // Code values
  /** List a dictionary's values (hierarchical; each carries its ``depth``). */
  listCodeValues: (dictId: string) =>
    apiGet<CodeValue[]>(`/v1/schedule/code-dictionaries/${encodeURIComponent(dictId)}/values/`),
  /** Add a value to a dictionary (optionally under a parent value). */
  createCodeValue: (dictId: string, body: CodeValueCreateBody) =>
    apiPost<CodeValue, CodeValueCreateBody>(
      `/v1/schedule/code-dictionaries/${encodeURIComponent(dictId)}/values/`,
      body,
    ),
  /** Delete a code value. */
  deleteCodeValue: (valueId: string) =>
    apiDelete(`/v1/schedule/code-values/${encodeURIComponent(valueId)}`),

  // User-defined fields (UDFs)
  /** List the project's user-defined fields. */
  listUdfs: (projectId: string) =>
    apiGet<ScheduleUdf[]>(`/v1/schedule/projects/${encodeURIComponent(projectId)}/udfs/`),
  /** Create a user-defined field in the project. */
  createUdf: (projectId: string, body: UdfCreateBody) =>
    apiPost<ScheduleUdf, UdfCreateBody>(
      `/v1/schedule/projects/${encodeURIComponent(projectId)}/udfs/`,
      body,
    ),
  /** Delete a user-defined field. */
  deleteUdf: (udfId: string) =>
    apiDelete(`/v1/schedule/udfs/${encodeURIComponent(udfId)}`),

  // Saved layouts
  /** List saved layouts visible to the caller for this schedule. */
  listLayouts: (scheduleId: string) =>
    apiGet<ScheduleLayout[]>(`/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/layouts/`),
  /** Create (save) a layout for this schedule. */
  createLayout: (scheduleId: string, body: LayoutCreateBody) =>
    apiPost<ScheduleLayout, LayoutCreateBody>(
      `/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/layouts/`,
      body,
    ),
  /** Delete a saved layout (owner only). */
  deleteLayout: (layoutId: string) =>
    apiDelete(`/v1/schedule/layouts/${encodeURIComponent(layoutId)}`),

  // Grouped grid
  /** Resolve a layout into a grouped, filtered, paged activity grid. */
  groupedActivities: (scheduleId: string, body: GroupedRequestBody) =>
    apiPost<GroupedResponse, GroupedRequestBody>(
      `/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/activities/grouped/`,
      body,
    ),

  /* ── T3.4 realtime collaboration ────────────────────────────────────── */

  /** Snapshot of who is currently connected to (editing) a schedule room. */
  getPresence: (scheduleId: string) =>
    apiGet<SchedulePresence>(
      `/v1/schedule/schedules/${encodeURIComponent(scheduleId)}/presence/`,
    ),
  /** The activity's current optimistic-concurrency revision token. */
  getActivityRevision: (activityId: string) =>
    apiGet<ActivityRevision>(
      `/v1/schedule/activities/${encodeURIComponent(activityId)}/revision/`,
    ),
  /**
   * Patch an activity only if ``baseRevision`` is still current. Resolves with
   * the up-to-date activity + new revision on apply / no-op. Rejects with an
   * ``ApiError``: status 409 (stale - body is ``RevisionConflict`` with the
   * authoritative revision + current state) or 422 (malformed base revision /
   * non-editable field).
   */
  guardedUpdateActivity: (
    activityId: string,
    baseRevision: number | null,
    fields: GuardedUpdateFields,
  ) =>
    apiPatch<GuardedUpdateResult, { base_revision: number | null; fields: GuardedUpdateFields }>(
      `/v1/schedule/activities/${encodeURIComponent(activityId)}/guarded/`,
      { base_revision: baseRevision, fields },
    ),
};
