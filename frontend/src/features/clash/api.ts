/**
 * API helpers for Clash Detection.
 *
 * Endpoints (mounted at /api/v1/clash):
 *   GET    /v1/clash/projects/{pid}/models
 *   GET    /v1/clash/projects/{pid}/runs/
 *   POST   /v1/clash/projects/{pid}/runs/
 *   GET    /v1/clash/projects/{pid}/runs/{rid}
 *   DELETE /v1/clash/projects/{pid}/runs/{rid}
 *   GET    /v1/clash/projects/{pid}/runs/{rid}/results
 *   PATCH  /v1/clash/projects/{pid}/runs/{rid}/results/{cid}
 *   POST   /v1/clash/projects/{pid}/runs/{rid}/export-bcf
 */

import { apiGet, apiPost, apiPatch, apiDelete, extractErrorMessageFromBody } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

export interface ClashModelOption {
  id: string;
  name: string;
  element_count: number;
  status: string | null;
}

export interface ClashMatrixCell {
  a: string;
  b: string;
  count: number;
  open_count: number;
}

export interface ClashLevelMatrixCell {
  a: number;
  b: number;
  count: number;
  open_count: number;
}

export interface ClashRunSummary {
  disciplines: string[];
  matrix: ClashMatrixCell[];
  /** Storey×storey grid — present on newer backends; optional so older
   *  payloads still type-check. */
  storeys?: number[];
  level_matrix?: ClashLevelMatrixCell[];
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  /** Severity histogram — present on newer backends; optional so older
   *  payloads still type-check (the KPI strip degrades gracefully). */
  by_severity?: Record<string, number>;
}

/** Coordination priority of a clash. Drives the table badge colour and the
 *  optional severity filter / sort. */
export type ClashSeverity = 'critical' | 'high' | 'medium' | 'low';

/** One collaboration note on a clash. The server stamps `author` + `ts`
 *  (and resolves `author_id`); the client only ever sends the text.
 *
 *  `reply_to` carries the `ts` of a parent comment when this one is a
 *  reply (Wave A3 threading). Legacy flat comments simply omit it. */
export interface ClashComment {
  author: string;
  author_id: string | null;
  /** ISO-8601 timestamp. */
  ts: string;
  text: string;
  /** Parent comment's `ts` when this is a reply; `null`/absent for top-level. */
  reply_to?: string | null;
}

/** One audit-log entry on a clash. Appended every time a triage field
 *  changes (status / severity / assignee / due_date) or a comment is
 *  added. Drives the DetailPanel Activity tab (Wave A3). */
export interface ClashHistoryEntry {
  /** ISO-8601 timestamp. */
  ts: string;
  /** User id of the actor (may be `"system"` for engine events). */
  actor: string;
  /** Field that changed — `status` / `severity` / `assigned_to` /
   *  `due_date` / `comment_add` / `bcf_import` / `bcf_topic_guid`. */
  field: string;
  /** Previous value (string-coerced) or `null` when none. */
  before: string | null;
  /** New value (string-coerced) or `null` when no natural pair (e.g. comment add). */
  after: string | null;
}

/** Which interference an engine pass reports — the BIM-coordination-tool-style
 *  "Type" rule selector. `both` is the back-compatible default. */
export type ClashType = 'hard' | 'clearance' | 'both';

export interface ClashRun {
  id: string;
  project_id: string;
  name: string;
  description?: string | null;
  model_ids: string[];
  clash_type?: ClashType;
  ignore_same_model?: boolean;
  tolerance_m: number;
  clearance_m: number;
  mode: string;
  discipline_filter: string[][] | null;
  status: string;
  error: string | null;
  element_count: number;
  total_clashes: number;
  summary: ClashRunSummary;
  created_by: string;
  created_at: string;
  completed_at: string | null;
}

export interface ClashRunListItem {
  id: string;
  name: string;
  description?: string | null;
  clash_type?: ClashType;
  status: string;
  model_ids: string[];
  element_count: number;
  total_clashes: number;
  created_at: string;
  completed_at: string | null;
}

export interface ClashResult {
  id: string;
  run_id: string;
  a_element_id: string;
  b_element_id: string;
  a_stable_id: string;
  b_stable_id: string;
  a_name: string;
  b_name: string;
  a_discipline: string;
  b_discipline: string;
  a_element_type?: string;
  b_element_type?: string;
  a_model_id: string;
  b_model_id: string;
  /** Storey index each element sits on (level clustering by the geometry
   *  loader). Null on legacy rows / pre-GLB models — facet rows treat
   *  null as a discrete "(no level)" bucket. */
  a_storey?: number | null;
  b_storey?: number | null;
  clash_type: string;
  penetration_m: number;
  distance_m: number;
  cx: number;
  cy: number;
  cz: number;
  status: string;
  /** Coordination priority. Newer backends always send it; older payloads
   *  may omit it, so callers default to `medium`. */
  severity?: ClashSeverity;
  assigned_to: string | null;
  /** ISO "YYYY-MM-DD" target resolution date, or null when unset. */
  due_date?: string | null;
  /** Collaboration thread (oldest → newest). Absent on older payloads. */
  comments?: ClashComment[];
  /** Stable engine signature — used by run-to-run comparison to match the
   *  same physical clash across runs. */
  signature?: string;
  /** Wave A3 — collaboration. User-id list subscribed to this clash;
   *  the DetailPanel "Watching" chip toggles the caller's membership. */
  watchers?: string[];
  /** Wave A3 — audit trail. Every status/severity/assignee/due-date
   *  change + comment add appends one entry; the DetailPanel Activity
   *  tab renders the list in reverse-chronological order. */
  history?: ClashHistoryEntry[];
  /** Wave A2 — engine-derived advisory annotations (non-authoritative).
   *  Currently `{ severity_suggestion?: 'critical' | 'high' | 'medium' }`
   *  on deep hard clashes; the UI shows a "Suggested" chip. Absent on
   *  older backends — callers default to `{}`. */
  meta?: { severity_suggestion?: ClashSeverity } & Record<string, unknown>;
  bcf_topic_guid: string | null;
  /** Wave A4 — run-scoped spatial cluster id (DBSCAN over centroids).
   *  `null` marks DBSCAN noise / legacy rows; the chip group filters
   *  results by matching this against the active cluster id. */
  cluster_id?: number | null;
  /** Client-only: original ordinal within the loaded result set, assigned
   *  during the review-table filter pass for the # column / idx sort. */
  __idx?: number;
}

export interface ClashResultPage {
  items: ClashResult[];
  total: number;
  offset: number;
  limit: number;
}

/** Grouping parameter the Set A / Set B facet lists are built from. The
 *  four built-ins plus the dynamic `property:<key>` form — any distinct
 *  element-property key the backend surfaced in `available_properties`. */
export type ClashGroupBy =
  | 'discipline'
  | 'type'
  | 'category'
  | 'ifc_entity'
  | `property:${string}`;

/** One side of a BIM-coordination-tool-style selection-set clash. A "set" is the
 *  union of the chosen disciplines / element types / categories / IFC
 *  entities + arbitrary element-property values — every chip (from
 *  whichever grouping parameter) widens it. */
export interface ClashSelectionSet {
  disciplines: string[];
  element_types: string[];
  categories: string[];
  ifc_entities: string[];
  /** Chips faceted by `property:<key>`, keyed by the bare property key.
   *  Additive/back-compatible — older backends ignore it; default `{}`. */
  properties: Record<string, string[]>;
}

export interface ClashCategoryItem {
  value: string;
  count: number;
}

/** One distinct element-property key surfaced across the selected models
 *  (already noise-filtered / capped / sorted server-side). */
export interface ClashPropertyKey {
  key: string;
  count: number;
}

export interface ClashCategories {
  /** The grouping parameter these `groups` were faceted by. */
  group_by: ClashGroupBy;
  /** Facet list for the requested grouping parameter. */
  groups: ClashCategoryItem[];
  /** Only the grouping params that actually have data across the
   *  selected models (IFC entity is absent on a pure-Revit project). */
  available_group_by: ClashGroupBy[];
  /** Distinct element-property keys (any of which can be picked as a
   *  `property:<key>` grouping parameter). Absent on older backends. */
  available_properties?: ClashPropertyKey[];
  /** Kept for backward compatibility. */
  element_types: ClashCategoryItem[];
  disciplines: ClashCategoryItem[];
}

/** Compact projection of a clash used by the run-to-run comparison view —
 *  enough to render a row + open it in 3D, without paging full results. */
export interface ClashResultSummary {
  id: string;
  a_name: string;
  b_name: string;
  clash_type: string;
  severity: ClashSeverity;
  penetration_m: number;
  distance_m: number;
  status: string;
  assigned_to: string | null;
}

/** GET …/runs/{rid}/compare?base_run_id=<uuid> response. `persistent`
 *  carries both sides so the UI can show status drift. */
export interface ClashCompare {
  new: ClashResultSummary[];
  resolved: ClashResultSummary[];
  persistent: { current: ClashResultSummary; base: ClashResultSummary }[];
  stats: {
    new: number;
    resolved: number;
    persistent: number;
    base_total: number;
    current_total: number;
  };
}

export interface ClashRunCreateBody {
  name?: string;
  description?: string | null;
  model_ids: string[];
  /** BIM-coordination-tool-style "Type": hard interpenetration only, clearance
   *  (proximity) only, or both. Defaults to `both` server-side. */
  clash_type?: ClashType;
  /** Federated noise filter — only report cross-model pairs. No effect
   *  on a single-model run. */
  ignore_same_model?: boolean;
  tolerance_m: number;
  clearance_m: number;
  mode: string;
  discipline_filter?: string[][] | null;
  set_a?: ClashSelectionSet | null;
  set_b?: ClashSelectionSet | null;
}

/** Wave A4 — one persisted spatial cluster of clashes within a run.
 *  ``dominant_disciplines`` is the discipline pair the label is keyed
 *  off of (used by the chip palette to colour by trade); ``storey`` is
 *  the dominant level index — `null` when none of the cluster's
 *  members resolved a storey. Both are advisory; the chip renders
 *  fine without them. */
export interface ClashCluster {
  cluster_id: number;
  label: string;
  size: number;
  dominant_disciplines: string[];
  storey: number | null;
}

/** Where a clash group can be turned into a tracked work item. */
export type ClashActionTarget = 'punchlist' | 'task';

/** AI-augmented draft for turning a clash cluster into a work item. The
 *  engine proposes; the coordinator reviews + confirms (AI proposes, human
 *  confirms). `confidence` (0..1) is advisory only - the UI shows it as a
 *  chip and never auto-applies a weak guess. */
export interface ClashGroupActionProposal {
  cluster_id: number;
  target: ClashActionTarget;
  title: string;
  description: string;
  priority: 'low' | 'medium' | 'high' | 'critical';
  suggested_assignee: string | null;
  member_count: number;
  dominant_disciplines: string[];
  storey: number | null;
  max_severity: ClashSeverity | null;
  confidence: number;
  /** True when this group already produced a linked work item; the UI then
   *  disables the confirm button and points at the existing one. */
  already_linked: boolean;
  existing_action_id: string | null;
  existing_action_target: ClashActionTarget | null;
}

/** Coordinator's confirmation body. Every field is optional and overrides
 *  the matching value from the proposal. */
export interface ClashGroupActionBody {
  target: ClashActionTarget;
  title?: string;
  description?: string;
  priority?: 'low' | 'medium' | 'high' | 'critical';
  assigned_to?: string | null;
  due_date?: string | null;
  advance_status?: boolean;
}

/** Result of creating a work item from a clash cluster. `created` is false
 *  (idempotent no-op) when the group already had a linked item. */
export interface ClashGroupActionResult {
  created: boolean;
  action_id: string;
  action_target: ClashActionTarget;
  cluster_id: number;
  results_linked: number;
  results_advanced: number;
}

/** Wave A4 — one per-discipline-pair tolerance override on a run. */
export interface ClashRule {
  id: string;
  discipline_a: string;
  discipline_b: string;
  tolerance_m: number;
  severity_override?: ClashSeverity | null;
  enabled: boolean;
}

/** Wave A4 — one engine-mined rule proposal. `rule` is null when there
 *  is no confident proposal (the wrapper list is empty in that case). */
export interface ClashRuleSuggestion {
  rule: ClashRule | null;
  reason: string;
  fp_count: number;
}

/** Wave A4 — one cell of the KPI discipline×discipline grid (incl.
 *  `open_share` ratio for the dashboard's "top pairs" table). */
export interface ClashDisciplinePairStat {
  a: string;
  b: string;
  count: number;
  open_count: number;
  open_share: number;
}

/** Item #23 — a reusable clash-run configuration template, scoped to a
 *  project. Snapshots every engine parameter a coordinator tunes (minus
 *  the model selection) so the same coordination policy can be relaunched
 *  with one click. `name` is unique per project. */
export interface ClashProfile {
  id: string;
  project_id: string;
  name: string;
  description?: string | null;
  clash_type: ClashType;
  ignore_same_model: boolean;
  tolerance_m: number;
  clearance_m: number;
  mode: string;
  discipline_filter: string[][] | null;
  set_a?: ClashSelectionSet | null;
  set_b?: ClashSelectionSet | null;
  rules: ClashRule[];
  spatial_grid_mm: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

/** Body for POST /projects/{pid}/profiles (save a config as a profile). */
export interface ClashProfileCreateBody {
  name: string;
  description?: string | null;
  clash_type?: ClashType;
  ignore_same_model?: boolean;
  tolerance_m?: number;
  clearance_m?: number;
  mode?: string;
  discipline_filter?: string[][] | null;
  set_a?: ClashSelectionSet | null;
  set_b?: ClashSelectionSet | null;
  rules?: ClashRule[];
  spatial_grid_mm?: number;
}

/** Body for PATCH /profiles/{id} — every field optional (partial update). */
export type ClashProfileUpdateBody = Partial<ClashProfileCreateBody>;

/** Body for POST /profiles/{id}/apply (launch a run from the profile). */
export interface ClashProfileApplyBody {
  model_ids: string[];
  name?: string;
  carry_forward?: boolean;
}

/** Item #23 — the grouping axis the run summary can be broken down by. */
export type ClashGroupingDimension =
  | 'discipline_pair'
  | 'level'
  | 'level_discipline'
  | 'discipline_system';

/** One labelled bucket in a 1-D grouping (e.g. clashes per level). */
export interface ClashGroupCount {
  key: string;
  count: number;
  open_count: number;
}

/** A discipline×discipline matrix scoped to a single storey level. */
export interface ClashLevelDisciplineGroup {
  level: number;
  cells: ClashMatrixCell[];
}

/** Item #23 — multi-dimensional grouping of a run's clashes. Exactly one
 *  payload is populated for the requested `dimension`. */
export interface ClashGroupedSummary {
  dimension: ClashGroupingDimension;
  disciplines: string[];
  matrix: ClashMatrixCell[];
  levels: ClashGroupCount[];
  level_disciplines: ClashLevelDisciplineGroup[];
  systems: string[];
  system_matrix: ClashMatrixCell[];
  /** Whether any clash resolved a building system — lets the UI hide the
   *  `discipline_system` option when there is nothing to show. */
  has_system_data: boolean;
}

/** Wave A4 — KPI dashboard projection returned by GET /runs/{id}/kpi. */
export interface ClashKpi {
  total: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  by_type: Record<string, number>;
  by_discipline_pair: ClashDisciplinePairStat[];
  /** `null` when no row has resolved yet (UI hides the MTTR tile). */
  mttr_hours: number | null;
  top_clashing_pairs: ClashDisciplinePairStat[];
}

export const clashApi = {
  models: (projectId: string) =>
    apiGet<ClashModelOption[]>(`/v1/clash/projects/${projectId}/models`),

  categories: (
    projectId: string,
    modelIds: string[],
    groupBy: ClashGroupBy = 'type',
  ) => {
    const q = new URLSearchParams();
    modelIds.forEach((m) => q.append('model_ids', m));
    q.set('group_by', groupBy);
    return apiGet<ClashCategories>(
      `/v1/clash/projects/${projectId}/categories?${q.toString()}`,
    );
  },

  listRuns: (projectId: string) =>
    apiGet<ClashRunListItem[]>(`/v1/clash/projects/${projectId}/runs/`),

  createRun: (projectId: string, body: ClashRunCreateBody) =>
    apiPost<ClashRun, ClashRunCreateBody>(
      `/v1/clash/projects/${projectId}/runs/`,
      body,
    ),

  getRun: (projectId: string, runId: string) =>
    apiGet<ClashRun>(`/v1/clash/projects/${projectId}/runs/${runId}`),

  deleteRun: (projectId: string, runId: string) =>
    apiDelete(`/v1/clash/projects/${projectId}/runs/${runId}`),

  listResults: (
    projectId: string,
    runId: string,
    params: {
      status?: string;
      clash_type?: string;
      discipline?: string;
      severity?: string;
      order_by?: string;
      offset?: number;
      limit?: number;
    } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.status) q.set('status', params.status);
    if (params.clash_type) q.set('clash_type', params.clash_type);
    if (params.discipline) q.set('discipline', params.discipline);
    if (params.severity) q.set('severity', params.severity);
    if (params.order_by) q.set('order_by', params.order_by);
    q.set('offset', String(params.offset ?? 0));
    q.set('limit', String(params.limit ?? 100));
    return apiGet<ClashResultPage>(
      `/v1/clash/projects/${projectId}/runs/${runId}/results?${q.toString()}`,
    );
  },

  /**
   * Page the results endpoint at the backend maximum (500 rows/request)
   * until `min(total, cap)` rows are loaded, the server returns a short
   * page, or the abort signal fires. Returns the accumulated rows plus the
   * server-reported full `total` so callers can show "first N of M".
   *
   * The backend enforces `limit ∈ [1, 500]` — never request more than
   * `SERVER_PAGE` per call.
   */
  loadAllResults: async (
    projectId: string,
    runId: string,
    opts: { cap?: number; signal?: AbortSignal } = {},
  ): Promise<{ items: ClashResult[]; total: number; capped: boolean }> => {
    const SERVER_PAGE = 500;
    const cap = opts.cap ?? 2000;
    const items: ClashResult[] = [];
    let total = 0;
    let offset = 0;
    // First page also gives us the authoritative `total`.
    // Loop: stop when we hit the cap, exhaust `total`, or get a short page.
    for (;;) {
      if (opts.signal?.aborted) {
        throw new DOMException('Aborted', 'AbortError');
      }
      const remaining = cap - items.length;
      if (remaining <= 0) break;
      const pageLimit = Math.min(SERVER_PAGE, remaining);
      const q = new URLSearchParams();
      q.set('offset', String(offset));
      q.set('limit', String(pageLimit));
      const page = await apiGet<ClashResultPage>(
        `/v1/clash/projects/${projectId}/runs/${runId}/results?${q.toString()}`,
        { signal: opts.signal },
      );
      total = page.total;
      items.push(...page.items);
      offset += page.items.length;
      // Short page (server has no more rows) or we've reached the total.
      if (page.items.length < pageLimit) break;
      if (offset >= total) break;
    }
    return { items, total, capped: items.length < total };
  },

  updateResult: (
    projectId: string,
    runId: string,
    resultId: string,
    body: {
      status?: string;
      /** Wave A2 — reclassify the coordination urgency. The engine
       *  seeds a value from geometry; the user has final say. */
      severity?: ClashSeverity;
      assigned_to?: string | null;
      due_date?: string | null;
      /** Append a comment — the server stamps author + ts and returns the
       *  updated result (incl. the new `comments` array). `reply_to`
       *  is the parent comment's `ts` when this one threads under it
       *  (Wave A3); omit for a top-level comment. The text may embed
       *  `<at>userId</at>` tokens to fan a mention notification out. */
      add_comment?: { text: string; reply_to?: string | null };
    },
  ) =>
    apiPatch<ClashResult>(
      `/v1/clash/projects/${projectId}/runs/${runId}/results/${resultId}`,
      body,
    ),

  /**
   * Apply ONE triage change (status / severity / assignee) to many clashes
   * in a single request. Backs the review-table bulk-actions toolbar so a
   * large selection no longer fires one PATCH per row (and invalidates the
   * results query once, not per row). Returns how many rows actually
   * changed plus how many were requested.
   */
  bulkUpdateResults: (
    projectId: string,
    runId: string,
    body: {
      result_ids: string[];
      status?: string;
      severity?: ClashSeverity;
      assigned_to?: string | null;
    },
  ) =>
    apiPatch<{ updated: number; requested: number }>(
      `/v1/clash/projects/${projectId}/runs/${runId}/results`,
      body,
    ),

  /** Diff the active run against an earlier one (same models/config).
   *  Returns new / resolved / persistent buckets + summary stats. */
  compare: (projectId: string, runId: string, baseRunId: string) =>
    apiGet<ClashCompare>(
      `/v1/clash/projects/${projectId}/runs/${runId}/compare?base_run_id=${encodeURIComponent(
        baseRunId,
      )}`,
    ),

  exportBcf: (
    projectId: string,
    runId: string,
    body: { result_ids?: string[] | null },
  ) =>
    apiPost<{ exported: number; skipped: number }>(
      `/v1/clash/projects/${projectId}/runs/${runId}/export-bcf`,
      body,
    ),

  /**
   * Stream the run's results as a server-rendered CSV and trigger a browser
   * download, honouring the same status/type/severity filters the review
   * table uses. Done with an authenticated `fetch` → blob → hidden anchor
   * (mirrors the takeoff CAD export in features/ai/api.ts) because the
   * endpoint returns `text/csv`, not JSON, so `apiGet` can't be used.
   */
  exportCsv: async (
    projectId: string,
    runId: string,
    filters: {
      status?: string;
      clash_type?: string;
      severity?: string;
    } = {},
  ): Promise<void> => {
    const q = new URLSearchParams();
    if (filters.status) q.set('status', filters.status);
    if (filters.clash_type) q.set('clash_type', filters.clash_type);
    if (filters.severity) q.set('severity', filters.severity);
    const qs = q.toString();
    const token = useAuthStore.getState().accessToken;
    const res = await fetch(
      `/api/v1/clash/projects/${projectId}/runs/${runId}/export-csv${
        qs ? `?${qs}` : ''
      }`,
      {
        method: 'GET',
        headers: {
          Accept: 'text/csv',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      },
    );
    if (!res.ok) {
      const body = await res
        .json()
        .catch(() => ({ detail: res.statusText }));
      throw new Error(extractErrorMessageFromBody(body) ?? 'CSV export failed');
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const disposition = res.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="?([^"]+)"?/);
    a.download = match?.[1] || `clash-results-${runId}.csv`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 203);
  },

  /**
   * Round-trip a `.bcfzip` back into clash triage state. Topics are
   * matched to existing :class:`ClashResult` rows by recomputed
   * signature (or `bcf_topic_guid`); unmatched topics are logged
   * server-side and counted. Mirrors the BCF module's own POST
   * /import shape — multipart/form-data with a single `file` field —
   * because that's the FastAPI form the backend exposes.
   */
  importBcf: async (
    projectId: string,
    runId: string,
    file: File,
  ): Promise<{ matched: number; unmatched: number; errors: number }> => {
    const fd = new FormData();
    fd.append('file', file);
    const token = useAuthStore.getState().accessToken;
    const res = await fetch(
      `/api/v1/clash/projects/${projectId}/runs/${runId}/import-bcf`,
      {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: fd,
      },
    );
    if (!res.ok) {
      const body = await res
        .json()
        .catch(() => ({ detail: res.statusText }));
      throw new Error(extractErrorMessageFromBody(body) ?? 'BCF import failed');
    }
    return (await res.json()) as {
      matched: number;
      unmatched: number;
      errors: number;
    };
  },

  /** Subscribe the calling user to a clash (idempotent). */
  watch: (projectId: string, runId: string, resultId: string) =>
    apiPost<{ watchers: string[]; watching: boolean }>(
      `/v1/clash/projects/${projectId}/runs/${runId}/results/${resultId}/watch`,
      undefined,
    ),

  /** Unsubscribe the calling user from a clash (idempotent). */
  unwatch: (projectId: string, runId: string, resultId: string) =>
    apiDelete<{ watchers: string[]; watching: boolean }>(
      `/v1/clash/projects/${projectId}/runs/${runId}/results/${resultId}/watch`,
    ),

  /**
   * List project members for the @mention autocomplete. Falls back to
   * an empty list when the caller isn't owner/admin (the endpoint
   * 403s for project viewers — that's the intentional access policy,
   * so we degrade silently rather than spam the console).
   */
  projectMembers: (projectId: string) =>
    apiGet<
      Array<{
        user_id: string;
        email: string;
        full_name?: string;
        role?: string;
        is_owner?: boolean;
      }>
    >(`/v1/projects/${projectId}/members/`).catch(
      () =>
        [] as Array<{
          user_id: string;
          email: string;
          full_name?: string;
          role?: string;
          is_owner?: boolean;
        }>,
    ),

  /** Wave A4 — spatial clusters discovered for this run. Empty list when
   *  the run pre-dates the cluster pass / had no clashes / every clash
   *  was DBSCAN noise — the chip group simply renders empty. */
  listClusters: (projectId: string, runId: string) =>
    apiGet<ClashCluster[]>(
      `/v1/clash/projects/${projectId}/runs/${runId}/clusters`,
    ),

  /** AI-augmented draft for turning a clash cluster into a work item.
   *  The coordinator reviews + confirms via `createClusterAction`. */
  clusterActionProposal: (
    projectId: string,
    runId: string,
    clusterId: number,
    target: ClashActionTarget = 'punchlist',
  ) => {
    const q = new URLSearchParams({ target });
    return apiGet<ClashGroupActionProposal>(
      `/v1/clash/projects/${projectId}/runs/${runId}/clusters/${clusterId}/action-proposal?${q.toString()}`,
    );
  },

  /** Create one punch item / task from a clash cluster, with link-back.
   *  Idempotent: a group with an existing item returns `created=false`. */
  createClusterAction: (
    projectId: string,
    runId: string,
    clusterId: number,
    body: ClashGroupActionBody,
  ) =>
    apiPost<ClashGroupActionResult, ClashGroupActionBody>(
      `/v1/clash/projects/${projectId}/runs/${runId}/clusters/${clusterId}/action`,
      body,
    ),

  /** Wave A4 — engine-mined rule proposals from the run's FP history.
   *  Empty when no discipline pair has crossed the suggestion threshold. */
  listRuleSuggestions: (projectId: string, runId: string) =>
    apiGet<ClashRuleSuggestion[]>(
      `/v1/clash/projects/${projectId}/runs/${runId}/rule-suggestions`,
    ),

  /** Wave A4 — append the proposed rule + re-evaluate existing results.
   *  Returns `{ rule_added, results_affected }`. */
  applyRuleSuggestion: (
    projectId: string,
    runId: string,
    body: { discipline_a: string; discipline_b: string; tolerance_m: number },
  ) =>
    apiPost<{ rule_added: boolean; results_affected: number }>(
      `/v1/clash/projects/${projectId}/runs/${runId}/apply-rule-suggestion`,
      body,
    ),

  /** Wave A4 — current rule set persisted on the run. */
  listRules: (projectId: string, runId: string) =>
    apiGet<ClashRule[]>(
      `/v1/clash/projects/${projectId}/runs/${runId}/rules`,
    ),

  /** Wave A4 — replace the entire rule list (idempotent PUT-style PATCH).
   *  Server caps at 500 entries. */
  replaceRules: (projectId: string, runId: string, rules: ClashRule[]) =>
    apiPatch<ClashRule[]>(
      `/v1/clash/projects/${projectId}/runs/${runId}/rules`,
      { rules },
    ),

  /** Wave A4 — aggregate dashboard payload for the KPI tab. */
  kpi: (projectId: string, runId: string) =>
    apiGet<ClashKpi>(`/v1/clash/projects/${projectId}/runs/${runId}/kpi`),

  // ── Item #23 — persistent clash profiles ──────────────────────────

  /** The project's reusable clash-run profile library (newest first). */
  listProfiles: (projectId: string) =>
    apiGet<ClashProfile[]>(`/v1/clash/projects/${projectId}/profiles`),

  /** One profile by id (404 if not in this project). */
  getProfile: (projectId: string, profileId: string) =>
    apiGet<ClashProfile>(
      `/v1/clash/projects/${projectId}/profiles/${profileId}`,
    ),

  /** Save a run configuration as a named profile (409 on a dup name). */
  createProfile: (projectId: string, body: ClashProfileCreateBody) =>
    apiPost<ClashProfile, ClashProfileCreateBody>(
      `/v1/clash/projects/${projectId}/profiles`,
      body,
    ),

  /** Patch a profile in place (only supplied fields change). */
  updateProfile: (
    projectId: string,
    profileId: string,
    body: ClashProfileUpdateBody,
  ) =>
    apiPatch<ClashProfile>(
      `/v1/clash/projects/${projectId}/profiles/${profileId}`,
      body,
    ),

  /** Delete a profile from the library. */
  deleteProfile: (projectId: string, profileId: string) =>
    apiDelete(`/v1/clash/projects/${projectId}/profiles/${profileId}`),

  /** Launch + execute a fresh clash run using the profile as a template.
   *  Returns the completed run (same shape as createRun). */
  applyProfile: (
    projectId: string,
    profileId: string,
    body: ClashProfileApplyBody,
  ) =>
    apiPost<ClashRun, ClashProfileApplyBody>(
      `/v1/clash/projects/${projectId}/profiles/${profileId}/apply`,
      body,
    ),

  /** Item #23 — multi-dimensional grouping of a run's clashes. */
  groupedSummary: (
    projectId: string,
    runId: string,
    dimension: ClashGroupingDimension = 'discipline_pair',
  ) => {
    const q = new URLSearchParams({ dimension });
    return apiGet<ClashGroupedSummary>(
      `/v1/clash/projects/${projectId}/runs/${runId}/summary?${q.toString()}`,
    );
  },
};
