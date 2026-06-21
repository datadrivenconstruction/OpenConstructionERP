/**
 * API helpers for BIM Hub.
 *
 * Endpoints:
 *   GET  /v1/bim_hub?project_id=X          — list models for a project
 *   POST /v1/bim_hub/upload                 — upload BIM data (DataFrame + optional DAE)
 *   GET  /v1/bim_hub/models/{id}/elements   — list elements for a model
 *   GET  /v1/bim_hub/models/{id}/geometry   — serve DAE geometry file
 */

import {
  apiGet,
  apiPost,
  apiPatch,
  apiDelete,
  extractErrorMessageFromBody,
  triggerDownload,
  getAuthToken,
} from '@/shared/lib/api';
import { isModuleLoaded } from '@/shared/lib/moduleProbe';
import { useAuthStore } from '@/stores/useAuthStore';
import type { BIMElementData, BIMModelData } from '@/shared/ui/BIMViewer';

/* ── Format helpers ────────────────────────────────────────────────────── */

/** Source formats that are 2D drawings, not 3D models (no mesh ever). */
const NON_3D_BIM_FORMATS = ['dwg', 'dxf', 'dgn'];

/**
 * True when a model's source format is a 2D drawing (DWG/DXF/DGN) that can
 * never carry 3D geometry. Such models belong to the DWG Takeoff module and
 * must never appear in the BIM 3D Takeoff filmstrip, picker or viewer. Mirrors
 * the backend `is_non_3d_format` guard so the UI stays correct even against a
 * stale cache. Empty / unknown formats are treated as 3D-eligible.
 */
export function isNon3DBimFormat(format: string | null | undefined): boolean {
  if (!format) return false;
  const fmt = format.trim().toLowerCase().replace(/^\./, '');
  return NON_3D_BIM_FORMATS.some((token) => fmt.includes(token));
}

/* ── Response Types ────────────────────────────────────────────────────── */

export interface BIMModelsResponse {
  items: BIMModelData[];
  total: number;
  /** Aggregate disk usage of conversion artifacts (GLB/DAE/parquet/thumbnails)
   *  across every model in the project, in megabytes.  Surfaced in the
   *  BIM page header chip so users can see persistence at a glance. */
  total_artifact_size_mb?: number;
  /** Aggregate disk usage of any retained original CAD uploads, MB.
   *  Always 0 on production (`keep_original_cad=false`); non-zero on dev
   *  installs that opt into keeping the raw uploads. */
  total_original_size_mb?: number;
  /** Short label of where the blobs live (e.g. `data/bim/` or
   *  `s3://oe-bim-prod/bim/`).  Drives the chip's leading text. */
  storage_root_label?: string;
}

export interface BIMElementsResponse {
  items: BIMElementData[];
  total: number;
}

/** One enriched element row carrying just the fields the "By progress"
 *  3D overlay needs: the element id and its `current_pct` — the latest
 *  percent-complete (0-100) of the BOQ position(s) it links to, computed
 *  by the backend as the MAX across linked positions. `null` means the
 *  element is unlinked or no progress has been recorded yet. */
export interface BIMElementProgressRow {
  id: string;
  current_pct: number | null;
  /** ISO-8601 recorded date of the headline progress entry (the same entry
   *  whose percentage is `current_pct`). `null` when there's no linked
   *  progress or the winning entry carries no recorded date. Drives the
   *  "as of <date>" line in the selected-element info panel. */
  current_pct_date: string | null;
}

export interface BIMElementProgressResponse {
  items: BIMElementProgressRow[];
  total: number;
}

/** Fetch the latest BOQ progress per element for a model.
 *
 *  Uses the enriched element listing (`skeleton=false`) so the backend
 *  resolves each element's BOQ links and folds the latest
 *  `ProgressEntry.percent_complete` onto `current_pct`. We only keep the
 *  `id` + `current_pct` pair here — the heavy property / relation payload
 *  is discarded — so the caller gets a compact map to drive the 3D
 *  colour ramp. Paginated server-side at 2000/page; we walk every page
 *  so the overlay covers the whole model. */
export async function fetchBIMElementProgress(
  modelId: string,
): Promise<BIMElementProgressResponse> {
  const pageSize = 2000;
  const rows: BIMElementProgressRow[] = [];
  let offset = 0;
  let total = 0;
  // Bound the walk defensively so a backend that ignores pagination can
  // never spin us forever (models cap well under 200k elements).
  for (let page = 0; page < 200; page += 1) {
    const params = new URLSearchParams({
      limit: String(pageSize),
      offset: String(offset),
    });
    const resp = await apiGet<{
      items: Array<{ id: string; current_pct?: number | null; current_pct_date?: string | null }>;
      total: number;
    }>(`/v1/bim_hub/models/${encodeURIComponent(modelId)}/elements/?${params.toString()}`);
    total = resp.total;
    for (const item of resp.items) {
      rows.push({
        id: item.id,
        current_pct: item.current_pct ?? null,
        current_pct_date: item.current_pct_date ?? null,
      });
    }
    offset += pageSize;
    if (resp.items.length < pageSize || offset >= total) break;
  }
  return { items: rows, total };
}

export interface BIMUploadResponse {
  model_id: string;
  element_count: number;
  storeys: string[];
  disciplines: string[];
  has_geometry: boolean;
}

export interface BIMCadUploadResponse {
  /** Nullable — preflight `converter_required` rejects return `null`
   *  because no BIMModel row is created in that path. */
  model_id: string | null;
  /** Nullable for the same reason as `model_id`. */
  name: string | null;
  format: string;
  file_size: number;
  /** Final status after processing. `'converter_required'` is a
   *  preflight reject (no file saved); `'needs_converter'` is the
   *  post-upload case where the file was accepted but could not
   *  be processed. */
  status:
    | 'processing'
    | 'ready'
    | 'degraded'
    | 'needs_converter'
    | 'error'
    // `empty_model`: the file was read cleanly but carries no physical
    // building elements (only spatial containers). A graceful, non-failure
    // outcome - not an error (#197).
    | 'empty_model'
    | 'converter_required'
    | string;
  /** Number of BIM elements extracted by the processor.  Always
   *  present in the backend response (defaults to 0 when no
   *  elements were extracted, e.g. unprocessable formats). */
  element_count: number;
  // ── Added in v1.4.7 (converter preflight + auto-install) ──────────
  /** Real backend error message from ``BIMModel.error_message`` —
   *  surfaced so the frontend can show the actual reason instead
   *  of a hardcoded generic string. */
  error_message?: string | null;
  /** Converter id (e.g. `"rvt"`) — present on `converter_required`
   *  and `needs_converter` so the UI can offer a one-click install. */
  converter_id?: string | null;
  /** Absolute API path that triggers the install — present alongside
   *  `converter_id` in the same statuses. */
  install_endpoint?: string | null;
  /** Human-readable message — present on `converter_required`
   *  preflight rejects. */
  message?: string | null;
}

/* ── Converter Management (BIM preflight + auto-install) ─────────────── */

/** Health states surfaced by the backend smoke test:
 *   - `ok` — binary loads and exits cleanly.
 *   - `failed` — binary doesn't load (DLL missing, perms, etc.).
 *   - `unknown` — install detected, smoke test not yet run (the
 *     `verify=true` query param triggers it).
 *   - `not_installed` — the binary isn't present on disk. */
export type BIMConverterHealth =
  | 'ok'
  | 'failed'
  | 'unknown'
  | 'not_installed';

/** Stable action ids returned by the backend so the UI can render the
 *  correct fix button. New ids are added here as the smoke test learns
 *  to detect more failure modes. */
export type BIMConverterAction =
  | 'install_converter'
  | 'reinstall_converter'
  | 'install_vc_redist'
  | 'unblock_files'
  | 'check_permissions'
  | 'manual_install_from_github';

/** Single DDC converter entry as returned by the backend
 *  `/v1/takeoff/converters/` endpoint. */
export interface BIMConverterInfo {
  /** Stable converter id — one of `'rvt'`, `'dwg'`, `'ifc'`, `'dgn'`. */
  id: string;
  name: string;
  description: string;
  engine: string;
  extensions: string[];
  exe: string;
  version: string;
  size_mb: number;
  installed: boolean;
  path: string | null;
  /** Smoke-test result. Always present from v2.6.23+ (older servers omit
   *  the field — frontend treats missing as `'unknown'`). */
  health?: BIMConverterHealth;
  /** Human-readable explanation when `health !== 'ok'`. */
  health_message?: string;
  /** Stable action ids the UI maps to fix buttons. */
  suggested_actions?: BIMConverterAction[];
}

/** Response payload of `GET /v1/takeoff/converters/`. */
export interface BIMConvertersResponse {
  converters: BIMConverterInfo[];
  installed_count: number;
  /** Number of converters where `health === 'ok'`. Only meaningful when
   *  the request was made with `verify=true`. */
  healthy_count?: number;
  total_count: number;
}

/** Result of `POST /v1/takeoff/converters/{id}/verify/` — force-runs the
 *  smoke test (bypasses the 5-minute cache) and returns fresh health. */
export interface BIMConverterVerifyResult {
  converter_id: string;
  installed: boolean;
  path: string | null;
  health: BIMConverterHealth;
  health_message: string;
  suggested_actions: BIMConverterAction[];
}

/** Result of `POST /v1/takeoff/converters/{id}/install/`.
 *
 * Hardening note (v2.6.22): the backend now always returns a structured
 * response — even on failure paths the body carries `installed: false` plus
 * a concrete `message` and (on Linux) `platform_unsupported: true` with
 * the apt commands the user should run.  The frontend MUST branch on
 * `installed` instead of treating any 2xx as success. */
export interface BIMConverterInstallResult {
  converter_id: string;
  installed: boolean;
  path?: string;
  already_installed?: boolean;
  size_bytes?: number;
  message: string;
  /** Linux / macOS — the OS has no Windows-style auto-install path. */
  platform_unsupported?: boolean;
  /** Linux only — apt package name and a copy-pasteable script. */
  apt_package?: string;
  instructions?: string;
  /** Linux only — true if `/etc/apt/sources.list.d/ddc.list` already
   *  exists, i.e. the user has the DDC apt source and only needs a
   *  single `apt install` line. The toast renders a shorter title in
   *  that case. */
  apt_source_present?: boolean;
  /** Linux only — predicted binary path after install
   *  (e.g. `/usr/bin/RvtExporter`). Surfaced in the toast so the user
   *  knows where the .deb will land before running apt. */
  expected_binary_path?: string | null;
  /** Whether the post-install smoke test passed (Windows only). */
  smoke_test_passed?: boolean;
  platform?: string;
  /** v8.8.0: the download now runs in the background so the request can't be
   *  aborted mid-download ("signal timed out") on slow servers / behind
   *  proxies. When true the POST returned immediately; watch
   *  ``install-progress`` for the terminal ``done``/``error`` stage instead
   *  of treating this response as the final outcome. */
  async_install?: boolean;
  /** True when this call kicked off a fresh background install. */
  started?: boolean;
  /** True when an install for this converter was already in flight. */
  already_running?: boolean;
  /** Initial background stage (``starting``) when ``async_install`` is true. */
  stage?: string;
}

const EMPTY_CONVERTERS: BIMConvertersResponse = {
  converters: [],
  installed_count: 0,
  total_count: 0,
  healthy_count: 0,
};

/** List every DDC converter and its install status.  Shared with the
 *  Quantities page — use the same `['bim-converters']` query key in
 *  any component that renders converter state so cache invalidations
 *  stay in sync.
 *
 *  Pass `verify: true` to also run the per-converter smoke test (cached
 *  5 min server-side). Without it, every installed converter reports
 *  `health: 'unknown'` and the UI shows neutral pills.
 *
 *  When the `oe_takeoff` module is disabled on the server (e.g. user
 *  toggled it off in the Modules page) the request would 404. We probe
 *  `/v1/modules/` once per session and short-circuit — that keeps the
 *  browser's network panel quiet instead of logging an expected 404. */
export async function fetchBIMConverters(
  options: { verify?: boolean } = {},
): Promise<BIMConvertersResponse> {
  if (!(await isModuleLoaded('oe_takeoff'))) {
    return EMPTY_CONVERTERS;
  }
  const url = options.verify
    ? '/v1/takeoff/converters/?verify=true'
    : '/v1/takeoff/converters/';
  try {
    return await apiGet<BIMConvertersResponse>(url);
  } catch (err: unknown) {
    const status = (err as { status?: number } | null)?.status;
    if (status === 404) {
      return EMPTY_CONVERTERS;
    }
    throw err;
  }
}

/** Force-run the smoke test for a single converter, bypassing the
 *  server-side cache. Used by the BIM page's "Re-check" button after
 *  the user manually fixed something (installed VCRedist, unblocked
 *  the files, ran as admin). */
export async function verifyBIMConverter(
  converterId: string,
): Promise<BIMConverterVerifyResult> {
  return apiPost<BIMConverterVerifyResult>(
    `/v1/takeoff/converters/${encodeURIComponent(converterId)}/verify/`,
    {},
  );
}

export interface ConverterVersionEntry {
  id: string;
  name: string;
  exe: string;
  installed: boolean;
  installed_path: string | null;
  installed_size: number | null;
  installed_sha: string | null;
  latest_size: number | null;
  latest_sha: string | null;
  is_outdated: boolean;
  download_url: string | null;
  html_url: string | null;
}

export interface ConverterVersionCheck {
  converters: ConverterVersionEntry[];
  any_outdated: boolean;
  network_ok: boolean;
  checked_at: string;
  ttl_seconds: number;
}

/** Compare each installed DDC converter against the latest on GitHub.
 *
 *  Backend computes git-blob SHA-1 of every locally-installed converter
 *  and matches against GitHub Contents API. Cached server-side for 6 h,
 *  so polling here is cheap. Mounted at the system level (not under the
 *  takeoff module) so it works even when ``oe_takeoff`` is disabled. */
export async function fetchConverterVersionCheck(): Promise<ConverterVersionCheck | null> {
  try {
    // Note: this is a system-level endpoint at /api/system/, not under /api/v1/.
    const r = await fetch('/api/system/converters/version-check', {
      headers: { Accept: 'application/json' },
    });
    if (!r.ok) return null;
    return (await r.json()) as ConverterVersionCheck;
  } catch {
    return null;
  }
}

/** Trigger an auto-install of a DDC converter from GitHub releases.
 *  The request is blocking on the backend (downloads + extracts +
 *  verifies) and typically takes 60–120 s for the RVT converter.
 *
 *  Pass ``force=true`` to bypass the "already installed" short-circuit
 *  and re-download even when a binary is already present — used by the
 *  "Update" button when the version-check banner reports an outdated
 *  converter SHA.
 *
 *  v8.8.0: the backend no longer downloads inline. The POST kicks off a
 *  background download and returns immediately (``async_install: true``),
 *  which is what fixed the user-reported "signal timed out" on slow Ubuntu
 *  servers - a 100-300 MB download could never finish inside any single
 *  request window (and a reverse proxy would cut it even sooner). This
 *  helper then polls the lightweight ``install-progress`` endpoint until the
 *  background task reaches a terminal stage and resolves with the final
 *  result, so every caller (and its in-flight progress bar) keeps working
 *  unchanged - just without one multi-minute HTTP request held open.
 */
export async function installBIMConverter(
  converterId: string,
  options: { force?: boolean } = {},
): Promise<BIMConverterInstallResult> {
  const qs = options.force ? '?force=true' : '';
  // The POST returns at once now, so a short, deterministic signal is enough
  // (guarded for SSR / test stubs without AbortSignal.timeout).
  const signal: AbortSignal | undefined =
    typeof AbortSignal !== 'undefined' &&
    typeof (AbortSignal as { timeout?: (ms: number) => AbortSignal }).timeout ===
      'function'
      ? (AbortSignal as unknown as { timeout: (ms: number) => AbortSignal }).timeout(
          60_000,
        )
      : undefined;
  let initial: BIMConverterInstallResult;
  try {
    initial = await apiPost<BIMConverterInstallResult>(
      `/v1/takeoff/converters/${encodeURIComponent(converterId)}/install/${qs}`,
      {},
      signal ? { signal } : undefined,
    );
  } catch (err) {
    // The install POST is meant to return at once, but on a busy single-worker
    // backend (e.g. the desktop build mid-BIM-load) it can still exceed the
    // signal, and a flaky link can drop it ("Failed to fetch"). In BOTH cases
    // the backend has very likely already spawned the background download, so
    // treating this as a hard failure is wrong - it spammed users with
    // repeated "signal timed out" toasts. Fall through to the progress poll,
    // which reports the real outcome (or a calm "still downloading"). Only a
    // genuine HTTP error (unknown converter, auth) - which carries a status -
    // is re-thrown.
    const e = err as { isTimeout?: boolean; name?: string; message?: string; status?: number };
    const isTransient =
      e?.isTimeout === true ||
      e?.name === 'AbortError' ||
      (typeof e?.status !== 'number' &&
        /timed out|failed to fetch|networkerror|load failed|aborted/i.test(e?.message ?? ''));
    if (!isTransient) throw err;
    initial = {
      converter_id: converterId,
      installed: false,
      async_install: true,
      message: '',
    } as BIMConverterInstallResult;
  }

  // Back-compat: an older backend ran the install inline and already returned
  // the terminal result; an "already installed" answer is terminal too.
  if (!initial.async_install) return initial;

  // Poll the background install to completion. Each poll is a cheap, fast GET
  // (its own short timeout), so no single request is ever held open for the
  // whole download - the resilient part of the fix.
  const POLL_MS = 1500;
  const MAX_WAIT_MS = 20 * 60 * 1000; // generous: RVT on a slow link
  const startedAt = Date.now();
  const sleep = (ms: number): Promise<void> =>
    new Promise((resolve) => setTimeout(resolve, ms));

  await sleep(POLL_MS);
  while (Date.now() - startedAt < MAX_WAIT_MS) {
    let prog: BIMConverterInstallProgress | null = null;
    try {
      prog = await fetchBIMConverterInstallProgress(converterId);
    } catch {
      // Transient poll failure (slow backend) - keep waiting.
      await sleep(POLL_MS);
      continue;
    }
    if (prog.stage === 'done' || prog.stage === 'error') {
      return {
        converter_id: converterId,
        installed: Boolean(prog.installed),
        path: prog.path,
        message: prog.message ?? initial.message ?? '',
        smoke_test_passed: prog.smoke_test_passed,
        platform: prog.platform,
        platform_unsupported: prog.platform_unsupported,
        apt_package: prog.apt_package,
        apt_source_present: prog.apt_source_present,
        instructions: prog.instructions,
        already_installed: false,
      };
    }
    if (!prog.active) {
      // Progress vanished (backend restart / TTL) with no terminal record.
      break;
    }
    await sleep(POLL_MS);
  }

  // Timed out waiting, or the progress feed dropped. Don't claim failure - the
  // install may still be finishing server-side; tell the caller to re-check.
  return {
    converter_id: converterId,
    installed: false,
    async_install: true,
    message:
      initial.message ||
      'The converter is still downloading in the background. Check the BIM converters panel in a moment.',
  };
}

/** Lightweight progress poll for an in-flight converter install.
 *  Returns ``{active: false}`` when no install is running, or
 *  ``{active: true, stage, current, total, bytes_done, file, started_at}``
 *  while files are downloading. The frontend polls every 500 ms while
 *  the install mutation is pending. */
export interface BIMConverterInstallProgress {
  active: boolean;
  /** Backend stages, in order: ``starting`` (background task spawned) →
   *  ``listing`` (resolving the file/package set) → ``downloading``
   *  (fetching files) → ``extracting`` (Windows has none; Linux unpacks .deb
   *  archives here) → ``verifying`` (post-install smoke test) → terminal
   *  ``done`` / ``error``. The terminal stages carry the outcome so the
   *  frontend can finalize without holding the install request open. */
  stage?:
    | 'starting'
    | 'listing'
    | 'downloading'
    | 'extracting'
    | 'verifying'
    | 'done'
    | 'error';
  current?: number;
  total?: number;
  bytes_done?: number;
  file?: string | null;
  started_at?: number;
  /** Terminal record fields (present when ``stage`` is ``done``/``error``). */
  installed?: boolean;
  message?: string;
  error?: string;
  instructions?: string;
  apt_package?: string;
  apt_source_present?: boolean;
  platform_unsupported?: boolean;
  smoke_test_passed?: boolean;
  path?: string;
  platform?: string;
  finished_at?: number;
}

export async function fetchBIMConverterInstallProgress(
  converterId: string,
): Promise<BIMConverterInstallProgress> {
  return apiGet<BIMConverterInstallProgress>(
    `/v1/takeoff/converters/${encodeURIComponent(converterId)}/install-progress/`,
  );
}

/* ── API Functions ─────────────────────────────────────────────────────── */

/** Fetch all BIM models for a project. */
export async function fetchBIMModels(projectId: string): Promise<BIMModelsResponse> {
  return apiGet<BIMModelsResponse>(`/v1/bim_hub/?project_id=${encodeURIComponent(projectId)}`);
}

/** Fetch a single BIM model by ID (used for status polling). */
export async function fetchBIMModel(modelId: string): Promise<BIMModelData> {
  return apiGet<BIMModelData>(`/v1/bim_hub/${encodeURIComponent(modelId)}`);
}

/** Re-schedule background CAD conversion for a model that previously failed.
 *  Returns immediately with status="scheduled"; the frontend's existing
 *  bim-models query polls and transitions the UI when the worker finishes.
 *  Backend resets status="processing" + clears error_message before kicking
 *  off the worker, so the UI flips to the processing overlay synchronously. */
export async function retryBIMModelProcessing(
  modelId: string,
): Promise<{ status: string; model_id: string; message?: string }> {
  return apiPost<{ status: string; model_id: string; message?: string }>(
    `/v1/bim_hub/${encodeURIComponent(modelId)}/retry/`,
    {},
  );
}

/** Fetch elements for a specific BIM model.
 *
 * Two modes:
 *   * `skeleton: true` — plain BIMElement rows, no enrichment joins. ~10×
 *     faster; used by the 3D viewer (it only needs id / mesh_ref / name /
 *     element_type / bbox for mesh matching). Server cap 50 000.
 *   * `skeleton: false` (default) — enriched with boq_links, linked
 *     documents / tasks / activities / requirements and validation
 *     results. Paginated (server cap 2000). Used by BOQ linking and the
 *     element list.
 *
 * A click in the viewer still resolves full Revit properties via
 * /dataframe/query/ against the Parquet, so selection cost is O(1) in
 * element count regardless of which mode fetched the list.
 */
export async function fetchBIMElements(
  modelId: string,
  opts?: {
    limit?: number;
    offset?: number;
    groupId?: string | null;
    skeleton?: boolean;
  },
): Promise<BIMElementsResponse> {
  const skeleton = opts?.skeleton ?? false;
  const limit = opts?.limit ?? (skeleton ? 50000 : 500);
  const offset = opts?.offset ?? 0;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (opts?.groupId) params.set('group_id', opts.groupId);
  if (skeleton) params.set('skeleton', 'true');
  return apiGet<BIMElementsResponse>(
    `/v1/bim_hub/models/${encodeURIComponent(modelId)}/elements/?${params.toString()}`,
  );
}

/** Fetch specific elements by their IDs (DB UUID or stable_id).
 *  Used by the BIM Quantity Picker to load only linked elements. */
export async function fetchBIMElementsByIds(
  modelId: string,
  elementIds: string[],
): Promise<BIMElementsResponse> {
  return apiPost<BIMElementsResponse, { element_ids: string[] }>(
    `/v1/bim_hub/models/${encodeURIComponent(modelId)}/elements/by-ids/`,
    { element_ids: elementIds },
  );
}

export interface BIMModelBOQLinkAggregate {
  boq_position_id: string;
  boq_id: string;
  boq_position_ordinal: string | null;
  boq_position_description: string | null;
  boq_position_quantity: number | null;
  boq_position_unit: string | null;
  boq_position_unit_rate: number | null;
  boq_position_total: number | null;
  link_type: string;
  confidence: string | null;
  element_ids: string[];
}

export interface BIMModelBOQLinksResponse {
  items: BIMModelBOQLinkAggregate[];
  total: number;
}

/** Aggregate all BOQ links for a model in one call.
 *  Powers the "Linked BOQ" panel, which needs roll-ups across the whole
 *  model — the viewer loads elements in skeleton mode (no boq_links),
 *  and the enriched path is capped at 2000 elements per page. */
export async function fetchBIMModelBOQLinks(
  modelId: string,
): Promise<BIMModelBOQLinksResponse> {
  return apiGet<BIMModelBOQLinksResponse>(
    `/v1/bim_hub/models/${encodeURIComponent(modelId)}/boq-links/`,
  );
}

/** Fetch the geometry file as a blob and return an object URL.
 *
 * Uses the Authorization header instead of a query-param token to avoid
 * leaking the JWT in logs, CDN caches, or error messages.  The caller
 * MUST call `URL.revokeObjectURL()` on the returned URL when done.
 */
export async function fetchGeometryBlobUrl(modelId: string): Promise<string> {
  const token = useAuthStore.getState().accessToken;
  // Cache-bust: geometry may have been re-generated with patched node names
  const url = `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/geometry/?_t=${Date.now()}`;
  const headers: HeadersInit = { Accept: '*/*', 'Cache-Control': 'no-cache' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const resp = await fetch(url, { headers });
  if (!resp.ok) {
    throw new Error(`Geometry fetch failed (HTTP ${resp.status})`);
  }
  const blob = await resp.blob();
  return URL.createObjectURL(blob);
}

/** Fetch the full Parquet row for a single element, keyed by its Revit
 *  ElementId (the Parquet `id` column).
 *
 *  The 3D viewer uses the lightweight "skeleton" element list
 *  (`fetchBIMElements(..., { skeleton: true })`) — five fields per row, no
 *  properties. When the user clicks a mesh the viewer calls this to pull
 *  the full ~45-1000 column row (all DDC-extracted Revit parameters) on
 *  demand. That keeps the initial load fast and lazy-loads detail only
 *  when needed.
 *
 *  `revitId` is typically `BIMElementData.mesh_ref`. For DDC-exported
 *  RVT / IFC this equals the DAE `<node id="...">` attribute and the
 *  Parquet row's `id`. Returns `null` when the Parquet has no row with
 *  that id (the element was filtered out of BIMElement by the category
 *  skip-list but still survives in Parquet).
 */
export async function fetchBIMElementProperties(
  modelId: string,
  revitId: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown> | null> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(
    `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/dataframe/query/`,
    {
      method: 'POST',
      headers,
      signal,
      body: JSON.stringify({
        filters: [{ column: 'id', op: '=', value: String(revitId) }],
        limit: 1,
      }),
    },
  );

  if (!resp.ok) {
    throw new Error(`Element properties fetch failed (HTTP ${resp.status})`);
  }
  const rows = (await resp.json()) as Record<string, unknown>[];
  return rows[0] ?? null;
}

/**
 * Schema row describing one column in the model's Parquet dataframe.
 * Returned by ``GET /models/{id}/dataframe/schema/``.
 */
export interface BIMDataframeColumn {
  name: string;
  type: string;
}

/** Fetch the column schema for the model's Parquet dataframe. Used by the
 *  property-search panel to populate the column dropdown. */
export async function fetchBIMDataframeSchema(
  modelId: string,
  signal?: AbortSignal,
): Promise<BIMDataframeColumn[]> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(
    `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/dataframe/schema/`,
    { method: 'GET', headers, signal },
  );
  if (!resp.ok) {
    throw new Error(`Dataframe schema fetch failed (HTTP ${resp.status})`);
  }
  const rows = (await resp.json()) as BIMDataframeColumn[];
  return rows;
}

/** Filter clause shape accepted by ``POST /models/{id}/dataframe/query/``. */
export interface BIMDataframeFilter {
  column: string;
  op: '=' | '!=' | '<' | '<=' | '>' | '>=' | 'LIKE' | 'IN' | 'NOT IN';
  value: string | number | (string | number)[];
}

export interface BIMDataframeQueryBody {
  columns?: string[];
  filters?: BIMDataframeFilter[];
  limit?: number;
}

/** Run a DuckDB query against the model's Parquet dataframe. Returns the
 *  matching rows verbatim — caller is responsible for picking the columns
 *  they need (typically ``id`` to drive viewport isolation). */
export async function queryBIMDataframe(
  modelId: string,
  body: BIMDataframeQueryBody,
  signal?: AbortSignal,
): Promise<Record<string, unknown>[]> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(
    `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/dataframe/query/`,
    {
      method: 'POST',
      headers,
      signal,
      body: JSON.stringify(body),
    },
  );
  if (!resp.ok) {
    throw new Error(`Dataframe query failed (HTTP ${resp.status})`);
  }
  return (await resp.json()) as Record<string, unknown>[];
}

/** @deprecated Use fetchGeometryBlobUrl() instead — this exposes the JWT in the URL. */
export function getGeometryUrl(modelId: string): string {
  const token = useAuthStore.getState().accessToken;
  const base = `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/geometry/`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

/** Upload BIM data (DataFrame + optional geometry file). */
export async function uploadBIMData(
  projectId: string,
  name: string,
  discipline: string,
  dataFile: File,
  geometryFile?: File | null,
  signal?: AbortSignal,
): Promise<BIMUploadResponse> {
  const formData = new FormData();
  formData.append('data_file', dataFile);
  if (geometryFile) {
    formData.append('geometry_file', geometryFile);
  }

  const params = new URLSearchParams({
    project_id: projectId,
    name,
    discipline,
  });

  const token = useAuthStore.getState().accessToken;
  const headers: HeadersInit = {
    Accept: 'application/json',
    'X-DDC-Client': 'OE/1.0',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`/api/v1/bim_hub/upload/?${params.toString()}`, {
      method: 'POST',
      headers,
      body: formData,
      signal,
    });
  } catch (networkErr) {
    // Re-throw AbortError as-is so callers can distinguish cancellation
    if (networkErr instanceof DOMException && networkErr.name === 'AbortError') throw networkErr;
    throw new Error(
      'Cannot connect to server. Please check that the backend is running and try again.',
    );
  }

  if (!response.ok) {
    let detail = `Upload failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(detail);
  }

  return response.json();
}

/** Delete a BIM model and all its elements. */
export async function deleteBIMModel(modelId: string): Promise<void> {
  await apiDelete(`/v1/bim_hub/${encodeURIComponent(modelId)}`);
}

/* ── BIM ↔ BOQ Linking ─────────────────────────────────────────────────── */

/** A single link between a BIM element and a BOQ position. */
export interface BOQElementLink {
  id: string;
  boq_position_id: string;
  bim_element_id: string;
  link_type: 'manual' | 'auto' | 'rule_based';
  confidence: string | null;
  rule_id: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Brief embedded in the element response: the linked BOQ position's key fields. */
export interface BOQElementLinkBrief {
  id: string;
  boq_position_id: string;
  boq_position_ordinal: string | null;
  boq_position_description: string | null;
  boq_position_quantity: number | null;
  boq_position_unit: string | null;
  boq_position_unit_rate: number | null;
  boq_position_total: number | null;
  link_type: 'manual' | 'auto' | 'rule_based';
  confidence: string | null;
}

export interface BOQElementLinkListResponse {
  items: BOQElementLink[];
  total: number;
}

export interface CreateBOQElementLinkRequest {
  boq_position_id: string;
  bim_element_id: string;
  link_type?: 'manual' | 'auto' | 'rule_based';
  confidence?: string;
  rule_id?: string;
  metadata?: Record<string, unknown>;
}

/** List every BIM element link attached to a given BOQ position. */
export async function listLinks(
  boqPositionId: string,
): Promise<BOQElementLinkListResponse> {
  return apiGet<BOQElementLinkListResponse>(
    `/v1/bim_hub/links/?boq_position_id=${encodeURIComponent(boqPositionId)}`,
  );
}

/** Resolve (or lazy-create) a BIMElement DB row from a mesh_ref / stable_id.
 *
 *  When the user clicks a mesh in the 3D viewer that was NOT returned by
 *  the standard BIMElement listing (e.g. DDC's Excel extract skipped the
 *  category — tapered roofs, planting, detail lines…), the frontend holds
 *  only a client-side stub id like `_unmatched_12`.  That id will fail UUID
 *  validation on POST /links/.  Call this first to swap the stub for a
 *  real BIMElement UUID; the backend pulls the row from Parquet and persists
 *  it so future operations treat it like any other element. */
export async function ensureBIMElement(
  modelId: string,
  ref: { meshRef?: string | null; stableId?: string | null },
): Promise<{ id: string }> {
  const payload: Record<string, string> = {};
  if (ref.meshRef) payload.mesh_ref = ref.meshRef;
  if (ref.stableId) payload.stable_id = ref.stableId;
  return apiPost<{ id: string }, Record<string, string>>(
    `/v1/bim_hub/models/${encodeURIComponent(modelId)}/ensure-element/`,
    payload,
  );
}

/** Matches a canonical 36-char UUID (8-4-4-4-12, hex + dashes). Anything
 *  else — notably the viewer's client-side `_unmatched_N` stubs and raw
 *  Revit numeric ids — must be resolved to a real BIMElement UUID via
 *  `ensureBIMElement` before it can travel through a UUID-typed endpoint
 *  (POST /links/, element-group element_ids, …). */
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Turn any viewer element into a persisted BIMElement UUID.
 *
 *  UUIDs pass through untouched.  Client-side stubs (`_unmatched_N`) and
 *  raw numeric ids hit the backend lazy-create endpoint keyed by
 *  `mesh_ref` (or `stable_id`).  Shared by AddToBOQModal and SaveGroupModal
 *  so element→BOQ links AND saved groups always reference real rows — a
 *  stub id stored verbatim in a group's `element_ids` would never resolve
 *  back to a member and the group would appear empty/broken on reload. */
export async function resolveElementUUID(
  modelId: string,
  el: {
    id: string;
    mesh_ref?: string | null;
    stable_id?: string | null;
  },
): Promise<string> {
  if (UUID_RE.test(el.id)) return el.id;
  const ref = {
    meshRef: el.mesh_ref ?? null,
    stableId: el.stable_id ?? null,
  };
  if (!ref.meshRef && !ref.stableId) {
    throw new Error(
      'This mesh has no Revit ElementId - cannot persist it. ' +
        'Re-upload the model so the viewer can attach a stable reference.',
    );
  }
  const { id } = await ensureBIMElement(modelId, ref);
  return id;
}

/** Create a new BIM ↔ BOQ link. Returns the created record. */
export async function createLink(
  payload: CreateBOQElementLinkRequest,
): Promise<BOQElementLink> {
  return apiPost<BOQElementLink, CreateBOQElementLinkRequest>(
    '/v1/bim_hub/links/',
    payload,
  );
}

/** Remove a BIM ↔ BOQ link by its row id. */
export async function deleteLink(linkId: string): Promise<void> {
  await apiDelete(`/v1/bim_hub/links/${encodeURIComponent(linkId)}`);
}

/* ── Quantity Maps (rule-based bulk linking) ───────────────────────────── */

/** Optional target for a quantity-map rule. */
export interface QuantityMapTarget {
  /** Existing position to link to (preferred). */
  position_id?: string;
  /** Existing position to link to, looked up by its ordinal inside the project. */
  position_ordinal?: string;
  /** If true and no position resolves, auto-create one with the rule's name. */
  auto_create?: boolean;
  /** Classification JSON to attach to the auto-created position. */
  classification?: Record<string, string>;
  /** Default unit rate for auto-created positions.  Typically populated
   *  via the "Suggest from CWICR" button which calls
   *  `/api/v1/costs/suggest-for-element/` and inserts the top match. */
  unit_rate?: string;
  /** Cost item id this rule was matched against — kept around so the
   *  estimator can audit which CWICR row supplied the rate. */
  cost_item_id?: string;
}

export interface BIMQuantityMap {
  id: string;
  org_id: string | null;
  project_id: string | null;
  name: string;
  name_translations: Record<string, string> | null;
  element_type_filter: string;
  property_filter: Record<string, string> | null;
  quantity_source: string;
  multiplier: string;
  unit: string;
  waste_factor_pct: string | null;
  boq_target: QuantityMapTarget | null;
  is_active: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface BIMQuantityMapListResponse {
  items: BIMQuantityMap[];
  total: number;
}

export type CreateBIMQuantityMapRequest = Omit<
  BIMQuantityMap,
  'id' | 'created_at' | 'updated_at'
>;

export type PatchBIMQuantityMapRequest = Partial<CreateBIMQuantityMapRequest>;

export interface QuantityMapApplyRequest {
  model_id: string;
  dry_run: boolean;
}

export interface QuantityMapApplyResultItem {
  element_id: string;
  stable_id: string;
  element_type: string;
  rule_id: string;
  rule_name: string;
  quantity_source: string;
  raw_quantity: number;
  adjusted_quantity: number;
  unit: string;
  boq_target: QuantityMapTarget | null;
}

export interface QuantityMapApplyResult {
  matched_elements: number;
  rules_applied: number;
  links_created: number;
  positions_created: number;
  results: QuantityMapApplyResultItem[];
}

/** List every quantity-map rule visible to the current user. */
export async function listQuantityMaps(
  offset = 0,
  limit = 100,
): Promise<BIMQuantityMapListResponse> {
  return apiGet<BIMQuantityMapListResponse>(
    `/v1/bim_hub/quantity-maps/?offset=${offset}&limit=${limit}`,
  );
}

/** Create a new quantity-map rule. */
export async function createQuantityMap(
  payload: CreateBIMQuantityMapRequest,
): Promise<BIMQuantityMap> {
  return apiPost<BIMQuantityMap, CreateBIMQuantityMapRequest>(
    '/v1/bim_hub/quantity-maps/',
    payload,
  );
}

/** Patch a quantity-map rule. */
export async function patchQuantityMap(
  mapId: string,
  payload: PatchBIMQuantityMapRequest,
): Promise<BIMQuantityMap> {
  return apiPatch<BIMQuantityMap, PatchBIMQuantityMapRequest>(
    `/v1/bim_hub/quantity-maps/${encodeURIComponent(mapId)}`,
    payload,
  );
}

/** Apply every active quantity-map rule to the given model.
 *
 * When `dry_run` is true (the default), the endpoint returns a preview of
 * what would be linked without writing anything.  When false, it creates
 * real `BOQElementLink` rows (and, for rules with `auto_create: true`,
 * creates fresh BOQ positions) inside a transaction per rule.
 */
export async function applyQuantityMaps(
  modelId: string,
  dryRun = true,
): Promise<QuantityMapApplyResult> {
  return apiPost<QuantityMapApplyResult, QuantityMapApplyRequest>(
    '/v1/bim_hub/quantity-maps/apply/',
    { model_id: modelId, dry_run: dryRun },
  );
}

/* ── BIM Element Groups (saved selections) ────────────────────────────── */

/** Filter predicate for a dynamic group.  Every field is optional and
 *  multi-valued where it makes sense.  An empty filter matches every
 *  element. */
export interface BIMGroupFilterCriteria {
  element_type?: string | string[];
  category?: string | string[];
  discipline?: string | string[];
  storey?: string | string[];
  name_contains?: string;
  property_filter?: Record<string, string>;
}

export interface BIMElementGroup {
  id: string;
  project_id: string;
  model_id: string | null;
  name: string;
  description: string | null;
  is_dynamic: boolean;
  filter_criteria: BIMGroupFilterCriteria;
  element_ids: string[];
  element_count: number;
  color: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  /** Resolved member element UUIDs (computed by the backend on read for
   *  dynamic groups; equal to `element_ids` for static groups). */
  member_element_ids: string[];
}

export interface BIMElementGroupCreate {
  name: string;
  description?: string;
  model_id?: string | null;
  is_dynamic?: boolean;
  filter_criteria?: BIMGroupFilterCriteria;
  element_ids?: string[];
  color?: string;
}

export type BIMElementGroupUpdate = Partial<BIMElementGroupCreate>;

/** List every saved element group for the project, optionally scoped to one model. */
export async function listElementGroups(
  projectId: string,
  modelId?: string | null,
): Promise<BIMElementGroup[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (modelId) params.set('model_id', modelId);
  return apiGet<BIMElementGroup[]>(
    `/v1/bim_hub/element-groups/?${params.toString()}`,
  );
}

/** Create a new element group.  Returns the created record with member ids resolved. */
export async function createElementGroup(
  projectId: string,
  payload: BIMElementGroupCreate,
): Promise<BIMElementGroup> {
  return apiPost<BIMElementGroup, BIMElementGroupCreate>(
    `/v1/bim_hub/element-groups/?project_id=${encodeURIComponent(projectId)}`,
    payload,
  );
}

/** Patch an existing element group.  When filter_criteria changes the
 *  member ids are recomputed and re-cached on the backend side. */
export async function updateElementGroup(
  groupId: string,
  payload: BIMElementGroupUpdate,
): Promise<BIMElementGroup> {
  return apiPatch<BIMElementGroup, BIMElementGroupUpdate>(
    `/v1/bim_hub/element-groups/${encodeURIComponent(groupId)}`,
    payload,
  );
}

/** Delete an element group.  Existing BIMElementLink rows referencing
 *  members of the group are NOT touched — the group is just metadata. */
export async function deleteElementGroup(groupId: string): Promise<void> {
  await apiDelete(`/v1/bim_hub/element-groups/${encodeURIComponent(groupId)}`);
}

/* ── Smart Views — canonical-format rule builder ─────────────────────── */

/** Operators supported by the Smart View rule evaluator.
 *
 *  String operators: =, !=, contains, starts_with, ends_with, regex, in,
 *  not_in, is_empty, is_not_empty.  Numeric: =, !=, >, <, >=, <=, between,
 *  in, not_in, is_empty, is_not_empty.  The UI shows / hides operators
 *  based on the property's inferred data_type. */
export type SmartViewOp =
  | '='
  | '!='
  | 'contains'
  | 'starts_with'
  | 'ends_with'
  | 'regex'
  | '>'
  | '<'
  | '>='
  | '<='
  | 'between'
  | 'in'
  | 'not_in'
  | 'is_empty'
  | 'is_not_empty';

/** One leaf rule in the tree — a single (field, op, value) predicate. */
export interface SmartViewLeaf {
  field: string;
  op: SmartViewOp;
  value?: unknown;
}

/** A group node — combines child rules with AND or OR. */
export interface SmartViewGroup {
  op: 'AND' | 'OR';
  rules: Array<SmartViewLeaf | SmartViewGroup>;
}

/** Property catalog entry returned by GET /smart-views/properties.
 *
 *  - field: canonical path (e.g. "geometry.area_m2", "properties.material")
 *  - group: Identity / Geometry / Quantities / Properties
 *  - data_type: drives operator + value-input pickers in the UI
 *  - source_formats: badges shown on each row ("RVT" / "IFC" / "DWG" …)
 *  - sample_values: distinct values seen in the model (caps at 25 by default)
 */
export interface SmartViewProperty {
  field: string;
  label: string;
  group: 'identity' | 'geometry' | 'quantities' | 'properties';
  data_type: 'string' | 'number' | 'enum' | 'boolean';
  source_formats: string[];
  sample_values: string[];
  distinct_count: number;
  truncated: boolean;
}

export interface SmartViewPropertyCatalog {
  model_id: string | null;
  source_format: string;
  element_count: number;
  entries: SmartViewProperty[];
}

export interface SmartViewPreviewResult {
  matched_count: number;
  sample_element_ids: string[];
  truncated: boolean;
  normalised_rule_tree: SmartViewGroup;
}

/** Fetch the property catalog for one model.  Used to seed the
 *  Property Picker dropdown in the Smart View builder. */
export async function fetchSmartViewProperties(
  modelId: string,
): Promise<SmartViewPropertyCatalog> {
  const qs = new URLSearchParams({ model_id: modelId });
  return apiGet<SmartViewPropertyCatalog>(
    `/v1/bim_hub/smart-views/properties?${qs.toString()}`,
  );
}

/** Evaluate a rule tree without saving — returns count + sample ids.
 *  Drives the live "234 elements match" counter in the builder. */
export async function previewSmartView(payload: {
  model_id?: string | null;
  project_id?: string | null;
  rule_tree?: SmartViewGroup | null;
  filter_criteria?: BIMGroupFilterCriteria | null;
  sample_limit?: number;
}): Promise<SmartViewPreviewResult> {
  return apiPost<SmartViewPreviewResult, typeof payload>(
    '/v1/bim_hub/smart-views/preview',
    payload,
  );
}

/* ── Cross-module link wrappers (Documents / Tasks / Schedule) ───────── */

/** A document ↔ BIM element link. */
export interface DocumentBIMLink {
  id: string;
  document_id: string;
  bim_element_id: string;
  link_type: 'manual' | 'auto';
  confidence: string | null;
  region_bbox: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DocumentBIMLinkListResponse {
  items: DocumentBIMLink[];
  total: number;
}

export interface CreateDocumentBIMLinkRequest {
  document_id: string;
  bim_element_id: string;
  link_type?: 'manual' | 'auto';
  confidence?: string;
  region_bbox?: Record<string, unknown>;
}

/** List documents linked to a BIM element. */
export async function listDocumentsForElement(
  elementId: string,
): Promise<DocumentBIMLinkListResponse> {
  return apiGet<DocumentBIMLinkListResponse>(
    `/v1/documents/bim-links/?element_id=${encodeURIComponent(elementId)}`,
  );
}

/** List BIM elements linked from a document. */
export async function listElementsForDocument(
  documentId: string,
): Promise<DocumentBIMLinkListResponse> {
  return apiGet<DocumentBIMLinkListResponse>(
    `/v1/documents/bim-links/?document_id=${encodeURIComponent(documentId)}`,
  );
}

/** Create a new document ↔ BIM element link. */
export async function createDocumentBIMLink(
  payload: CreateDocumentBIMLinkRequest,
): Promise<DocumentBIMLink> {
  return apiPost<DocumentBIMLink, CreateDocumentBIMLinkRequest>(
    '/v1/documents/bim-links/',
    payload,
  );
}

/** Remove a document ↔ BIM element link by id. */
export async function deleteDocumentBIMLink(linkId: string): Promise<void> {
  await apiDelete(`/v1/documents/bim-links/${encodeURIComponent(linkId)}`);
}

/* ── Tasks ↔ BIM element wrappers ────────────────────────────────────── */

export interface TaskBimLinkRequest {
  bim_element_ids: string[];
}

/** Replace the bim_element_ids list on a task. */
export async function updateTaskBIMLinks(
  taskId: string,
  bimElementIds: string[],
): Promise<unknown> {
  return apiPatch<unknown, TaskBimLinkRequest>(
    `/v1/tasks/${encodeURIComponent(taskId)}/bim-links`,
    { bim_element_ids: bimElementIds },
  );
}

/** List tasks that include the given BIM element id. */
export async function listTasksForElement(
  bimElementId: string,
  projectId?: string,
): Promise<unknown> {
  const params = new URLSearchParams({ bim_element_id: bimElementId });
  if (projectId) params.set('project_id', projectId);
  return apiGet<unknown>(`/v1/tasks/?${params.toString()}`);
}

/* ── Schedule activity ↔ BIM element wrappers ────────────────────────── */

export interface ActivityBimLinkRequest {
  bim_element_ids: string[];
}

/** Replace the bim_element_ids list on a schedule activity. */
export async function updateActivityBIMLinks(
  activityId: string,
  bimElementIds: string[],
): Promise<unknown> {
  return apiPatch<unknown, ActivityBimLinkRequest>(
    `/v1/schedule/activities/${encodeURIComponent(activityId)}/bim-links`,
    { bim_element_ids: bimElementIds },
  );
}

/** List schedule activities that include the given BIM element id. */
export async function listActivitiesForElement(
  bimElementId: string,
  projectId: string,
): Promise<unknown> {
  const params = new URLSearchParams({
    element_id: bimElementId,
    project_id: projectId,
  });
  return apiGet<unknown>(
    `/v1/schedule/activities/by-bim-element/?${params.toString()}`,
  );
}

/** Upload a raw CAD file (RVT, IFC, DWG, DGN, FBX, OBJ, 3DS) for background processing. */
export async function uploadCADFile(
  projectId: string,
  name: string,
  discipline: string,
  file: File,
  signal?: AbortSignal,
  conversionDepth?: 'standard' | 'medium' | 'complete',
): Promise<BIMCadUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);

  const qp: Record<string, string> = { project_id: projectId, name, discipline };
  if (conversionDepth) qp.conversion_depth = conversionDepth;
  const params = new URLSearchParams(qp);

  const token = useAuthStore.getState().accessToken;
  const headers: HeadersInit = {
    Accept: 'application/json',
    'X-DDC-Client': 'OE/1.0',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`/api/v1/bim_hub/upload-cad/?${params.toString()}`, {
      method: 'POST',
      headers,
      body: formData,
      signal,
    });
  } catch (networkErr) {
    // Re-throw AbortError as-is so callers can distinguish cancellation
    if (networkErr instanceof DOMException && networkErr.name === 'AbortError') throw networkErr;
    throw new Error(
      'Cannot connect to server. Please check that the backend is running and try again.',
    );
  }

  if (!response.ok) {
    let detail = `Upload failed (HTTP ${response.status})`;
    try {
      const body = await response.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(detail);
  }

  return response.json();
}

/** Trigger background generation of a single PDF that combines every
 *  sheet/view extracted from the uploaded CAD file.  The request itself
 *  is non-blocking — the backend schedules the job and returns
 *  immediately.  The resulting PDF is saved to the project's Documents
 *  module once ready. */
export async function generateBIMPDFSheets(
  modelId: string,
): Promise<{ status: string; model_id: string }> {
  return apiPost<{ status: string; model_id: string }>(
    `/v1/bim_hub/${encodeURIComponent(modelId)}/generate-pdf-sheets/`,
    {},
  );
}

/* ── BIM Requirements Import/Export ─────────────────────────────────── */

export interface BIMRequirementSetResponse {
  id: string;
  project_id: string;
  name: string;
  description: string;
  source_format: string;
  source_filename: string;
  created_by: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface BIMRequirementResponse {
  id: string;
  requirement_set_id: string;
  element_filter: Record<string, unknown>;
  property_group: string | null;
  property_name: string;
  constraint_def: Record<string, unknown>;
  context: Record<string, unknown> | null;
  source_format: string;
  source_ref: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface BIMRequirementSetDetail extends BIMRequirementSetResponse {
  requirements: BIMRequirementResponse[];
}

export interface BIMRequirementImportResult {
  requirement_set_id: string;
  name: string;
  source_format: string;
  total_requirements: number;
  errors: Array<{ row?: number; field?: string; msg?: string }>;
  warnings: Array<{ row?: number; field?: string; msg?: string }>;
  metadata: Record<string, unknown>;
}

/** Upload and import a BIM requirements file. */
export async function importBIMRequirements(
  projectId: string,
  file: File,
  name?: string,
): Promise<BIMRequirementImportResult> {
  const formData = new FormData();
  formData.append('file', file);

  let url = `/v1/bim_requirements/import/upload/?project_id=${encodeURIComponent(projectId)}`;
  if (name) {
    url += `&name=${encodeURIComponent(name)}`;
  }

  const token = useAuthStore.getState().accessToken;
  const reqHeaders: Record<string, string> = {};
  if (token) reqHeaders['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(`/api${url}`, { method: 'POST', headers: reqHeaders, body: formData });
  if (!resp.ok) {
    let detail = `Import failed (HTTP ${resp.status})`;
    try {
      const body = await resp.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      // ignore json parse error
    }
    throw new Error(detail);
  }
  return resp.json();
}

/** List BIM requirement sets for a project. */
export async function fetchBIMRequirementSets(
  projectId: string,
): Promise<BIMRequirementSetResponse[]> {
  return apiGet<BIMRequirementSetResponse[]>(
    `/v1/bim_requirements/sets/?project_id=${encodeURIComponent(projectId)}`,
  );
}

/** Get a BIM requirement set with all requirements. */
export async function fetchBIMRequirementSetDetail(
  setId: string,
): Promise<BIMRequirementSetDetail> {
  return apiGet<BIMRequirementSetDetail>(
    `/v1/bim_requirements/sets/${encodeURIComponent(setId)}/`,
  );
}

/** Delete a BIM requirement set. */
export async function deleteBIMRequirementSet(setId: string): Promise<void> {
  await apiDelete(`/v1/bim_requirements/sets/${encodeURIComponent(setId)}/`);
}

/** Download the BIM requirements Excel template URL.
 *  @deprecated A bare `<a href>` to this GET endpoint sends no Authorization
 *  header and 401s. Use {@link downloadBIMRequirementsTemplate} instead. */
export function bimRequirementsTemplateUrl(): string {
  return '/api/v1/bim_requirements/template/';
}

/** Export a BIM requirement set as Excel (returns action URL for POST).
 *  @deprecated The endpoint is POST-only and auth is Bearer-only, so a
 *  plain `<a href>` 405s/401s. Use {@link exportBIMRequirementSetExcel}. */
export function bimRequirementsExportExcelUrl(setId: string, language = 'en'): string {
  return `/api/v1/bim_requirements/export/${encodeURIComponent(setId)}/excel/?language=${language}`;
}

/** Export a BIM requirement set as IDS XML (returns action URL for POST).
 *  @deprecated POST-only + Bearer-only auth. Use {@link exportBIMRequirementSetIds}. */
export function bimRequirementsExportIdsUrl(setId: string): string {
  return `/api/v1/bim_requirements/export/${encodeURIComponent(setId)}/ids/`;
}

/** Pull a filename out of a Content-Disposition header, falling back to a
 *  caller-supplied default. Shared by the three requirement downloads. */
function filenameFromContentDisposition(resp: Response, fallback: string): string {
  const cd = resp.headers.get('content-disposition') || '';
  const match = cd.match(/filename="?([^";]+)"?/i);
  return match?.[1] || fallback;
}

/** Common authenticated-blob fetch for the requirement export/template
 *  endpoints. These are POST-only (export) or auth-guarded GET (template);
 *  a bare anchor click carries no Bearer token, so we fetch the blob with
 *  the JWT ourselves and trigger a synthetic download. Throws on HTTP
 *  error with the backend's message when available. */
async function downloadRequirementBlob(
  url: string,
  method: 'GET' | 'POST',
  fallbackName: string,
): Promise<void> {
  const token = getAuthToken();
  const headers: Record<string, string> = { Accept: '*/*' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const init: RequestInit = { method, headers };
  if (method === 'POST') {
    headers['Content-Type'] = 'application/json';
    init.body = '{}';
  }
  const resp = await fetch(url, init);
  if (!resp.ok) {
    let detail = `Download failed (HTTP ${resp.status})`;
    try {
      const body = await resp.json();
      detail = extractErrorMessageFromBody(body) ?? detail;
    } catch {
      /* ignore parse errors — keep the HTTP-status fallback */
    }
    throw new Error(detail);
  }
  const blob = await resp.blob();
  triggerDownload(blob, filenameFromContentDisposition(resp, fallbackName));
}

/** Download the BIM requirements Excel template via an authenticated fetch. */
export async function downloadBIMRequirementsTemplate(): Promise<void> {
  await downloadRequirementBlob(
    bimRequirementsTemplateUrl(),
    'GET',
    'bim_requirements_template.xlsx',
  );
}

/** Export a requirement set as a formatted Excel file (authenticated POST). */
export async function exportBIMRequirementSetExcel(
  setId: string,
  filename: string,
  language = 'en',
): Promise<void> {
  await downloadRequirementBlob(
    bimRequirementsExportExcelUrl(setId, language),
    'POST',
    `${filename || 'requirements'}.xlsx`,
  );
}

/** Export a requirement set as IDS XML (authenticated POST). */
export async function exportBIMRequirementSetIds(
  setId: string,
  filename: string,
): Promise<void> {
  await downloadRequirementBlob(
    bimRequirementsExportIdsUrl(setId),
    'POST',
    `${filename || 'requirements'}.ids`,
  );
}

/* ── BIM Requirements — model compliance validation ─────────────────── */

/** One requirement's outcome when a set is validated against a BIM model.
 *  Mirrors backend ``RequirementCheckResult``. */
export interface BIMRequirementCheckResult {
  requirement_id: string;
  property_group: string | null;
  property_name: string;
  element_filter: Record<string, unknown>;
  constraint_def: Record<string, unknown>;
  /** "pass" | "fail" | "not_applicable". */
  status: string;
  matched_elements: number;
  compliant_elements: number;
  non_compliant_elements: number;
  details: string;
}

/** Compliance report for a requirement set checked against a BIM model.
 *  Mirrors backend ``RequirementValidationResponse``. */
export interface BIMRequirementValidationResult {
  requirement_set_id: string;
  requirement_set_name: string;
  model_id: string;
  total_requirements: number;
  passed: number;
  failed: number;
  not_applicable: number;
  compliance_ratio: number;
  results: BIMRequirementCheckResult[];
}

/** Validate a BIM model's elements against a requirement set. Calls the
 *  real ``POST /validate/{set_id}/?model_id=...`` endpoint and returns the
 *  pass/fail/not-applicable compliance report. */
export async function validateBIMRequirementSet(
  setId: string,
  modelId: string,
): Promise<BIMRequirementValidationResult> {
  return apiPost<BIMRequirementValidationResult>(
    `/v1/bim_requirements/validate/${encodeURIComponent(setId)}/?model_id=${encodeURIComponent(modelId)}`,
    {},
  );
}

/* ── Asset Register (v2.3.0) ──────────────────────────────────────────── */

/** Asset-info payload persisted on a BIMElement row.
 *
 *  Every field is optional because assets evolve: a row is "tracked" as
 *  soon as *any* field gets a value. Sending an explicit `null` or
 *  empty-string clears a key from the stored JSON.
 */
export interface AssetInfoPayload {
  manufacturer?: string | null;
  model?: string | null;
  serial_number?: string | null;
  installation_date?: string | null;
  warranty_until?: string | null;
  operational_status?: string | null;
  parent_system?: string | null;
  notes?: string | null;
  /** Allow free-form keys — avoid dropping unknown fields on round-trip. */
  [key: string]: string | null | undefined;
}

/** Summary row returned by `GET /v1/bim_hub/assets`. */
export interface AssetSummary {
  id: string;
  stable_id: string;
  element_type: string;
  name: string | null;
  model_id: string;
  model_name: string;
  project_id: string;
  asset_info: AssetInfoPayload;
}

export interface AssetListResponse {
  items: AssetSummary[];
  total: number;
}

/** List all tracked assets for a project.
 *
 *  * `search` does a JSON substring match across manufacturer / model /
 *    serial / notes — case-insensitive.
 *  * `operationalStatus` filters by the stored `operational_status` key
 *    (e.g. `"operational"`, `"under_maintenance"`, `"decommissioned"`).
 */
export async function listTrackedAssets(
  projectId: string,
  opts?: {
    search?: string;
    operationalStatus?: string;
    offset?: number;
    limit?: number;
  },
): Promise<AssetListResponse> {
  const params = new URLSearchParams({
    project_id: projectId,
    offset: String(opts?.offset ?? 0),
    limit: String(opts?.limit ?? 200),
  });
  if (opts?.search) params.set('search', opts.search);
  if (opts?.operationalStatus) params.set('operational_status', opts.operationalStatus);
  // BUG-UI07: backend route is `/assets` (no trailing slash). With the
  // trailing slash FastAPI dispatches to `/{model_id}` instead, returning
  // 404 for "assets" as a UUID. Verified against /openapi.json.
  return apiGet<AssetListResponse>(`/v1/bim_hub/assets?${params.toString()}`);
}

/** Patch asset-info on a BIMElement. Partial merge — unspecified keys
 *  are preserved; `null`/empty string clears a key; non-empty value
 *  auto-flips `is_tracked_asset=true` unless the caller explicitly
 *  overrides it via `isTrackedAsset`. */
export async function updateElementAssetInfo(
  elementId: string,
  assetInfo: AssetInfoPayload,
  isTrackedAsset?: boolean,
): Promise<AssetSummary> {
  const body: { asset_info: AssetInfoPayload; is_tracked_asset?: boolean } = {
    asset_info: assetInfo,
  };
  if (isTrackedAsset !== undefined) body.is_tracked_asset = isTrackedAsset;
  // BUG-UI07: backend route has no trailing slash — see listTrackedAssets above.
  return apiPatch<AssetSummary, typeof body>(
    `/v1/bim_hub/assets/${encodeURIComponent(elementId)}/asset-info`,
    body,
  );
}

/** URL to the COBie UK 2.4 XLSX export for a BIM model.
 *  Backend route is `/export/cobie.xlsx` — NO trailing slash. With one,
 *  FastAPI 307-redirects and the browser drops the Authorization header. */
export function cobieExportUrl(modelId: string): string {
  return `/api/v1/bim_hub/models/${encodeURIComponent(modelId)}/export/cobie.xlsx`;
}

/** Download the COBie XLSX with the current user's JWT.
 *  `<a href>` clicks don't carry Authorization headers, so we fetch the
 *  blob ourselves and trigger a synthetic download. Throws on HTTP error. */
export async function downloadCobieXlsx(
  modelId: string,
  filename = 'cobie.xlsx',
): Promise<void> {
  const token = useAuthStore.getState().accessToken;
  const headers: HeadersInit = {
    Accept:
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream',
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(cobieExportUrl(modelId), { headers });
  if (!resp.ok) {
    let detail = '';
    try {
      detail = (await resp.text()).slice(0, 200);
    } catch {
      /* ignore */
    }
    throw new Error(`COBie export failed (HTTP ${resp.status}) ${detail}`);
  }
  const cd = resp.headers.get('content-disposition') || '';
  const match = cd.match(/filename="?([^";]+)"?/i);
  const finalName = match?.[1] || filename;
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = finalName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/* ── Model version diff ────────────────────────────────────────────────────
 *
 * Read-only client for the backend's existing per-element model diff
 * (`bim_hub` service `compute_diff`). We never reshape or recompute the
 * diff — these helpers only surface what the API already returns.
 *
 * Endpoints:
 *   POST /v1/bim_hub/models/{new_id}/diff/{old_id}  → compute (idempotent)
 *   GET  /v1/bim_hub/diffs/{diff_id}                → fetch existing
 */

/** One changed field inside a modified element (matches the service shape). */
export interface BIMDiffFieldChange {
  field: string;
  old: unknown;
  new: unknown;
}

/** A modified element entry from `diff_details.modified`. */
export interface BIMDiffModifiedEntry {
  stable_id: string;
  element_type: string | null;
  changes: BIMDiffFieldChange[];
}

/** An added / deleted element entry from `diff_details`. */
export interface BIMDiffSimpleEntry {
  stable_id: string;
  element_type: string | null;
  name: string | null;
}

export interface BIMModelDiffSummary {
  unchanged: number;
  modified: number;
  added: number;
  deleted: number;
}

export interface BIMModelDiffDetails {
  modified: BIMDiffModifiedEntry[];
  added: BIMDiffSimpleEntry[];
  deleted: BIMDiffSimpleEntry[];
}

export interface BIMModelDiff {
  id: string;
  old_model_id: string;
  new_model_id: string;
  diff_summary: BIMModelDiffSummary;
  diff_details: BIMModelDiffDetails | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Compute (or return the cached) diff between a newer and an older model
 *  version. The backend de-dupes by model pair so this is safe to call
 *  repeatedly. */
export async function computeBIMModelDiff(
  newModelId: string,
  oldModelId: string,
): Promise<BIMModelDiff> {
  return apiPost<BIMModelDiff>(
    `/v1/bim_hub/models/${encodeURIComponent(newModelId)}/diff/${encodeURIComponent(oldModelId)}`,
    {},
  );
}

/** Fetch a previously-computed diff by its id. */
export async function fetchBIMModelDiff(diffId: string): Promise<BIMModelDiff> {
  return apiGet<BIMModelDiff>(`/v1/bim_hub/diffs/${encodeURIComponent(diffId)}`);
}
