// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for BCF (BIM Collaboration Format) issues.
 *
 * BCF is an open standard for exchanging model-based issues (topics,
 * comments and camera viewpoints) between tools. These helpers mirror the
 * backend REST surface exactly - see backend/app/modules/bcf/router.py and
 * schemas.py. The wire shapes are the API schemas, deliberately decoupled
 * from the on-the-wire BCF-XML element names.
 *
 * Endpoints (mounted at /api/v1/bcf):
 *   GET    /projects/{project_id}/topics/                         list
 *   POST   /projects/{project_id}/topics/                         create
 *   GET    /projects/{project_id}/topics/{guid}                   read
 *   PUT    /projects/{project_id}/topics/{guid}                   update
 *   DELETE /projects/{project_id}/topics/{guid}                   delete
 *   POST   /projects/{project_id}/topics/{guid}/comments/         add comment
 *   PUT    /projects/{project_id}/topics/{guid}/comments/{id}     edit comment
 *   DELETE /projects/{project_id}/topics/{guid}/comments/{id}     delete comment
 *   POST   /projects/{project_id}/topics/{guid}/viewpoints/       add viewpoint
 *   GET    .../viewpoints/{vp_guid}/snapshot                      snapshot PNG
 *   GET    /projects/{project_id}/export?version=2.1|3.0          .bcfzip
 *   POST   /projects/{project_id}/export                          .bcfzip (selection)
 *   POST   /projects/{project_id}/import                          .bcfzip
 *
 * Note: the backend uses PUT (not PATCH) for topic and comment updates.
 */

import {
  apiGet,
  apiPost,
  apiPut,
  apiDelete,
  API_BASE,
  getAuthToken,
  extractErrorMessageFromBody,
} from '@/shared/lib/api';

const enc = encodeURIComponent;

/* ── Camera primitives (mirror bcf/schemas.py) ─────────────────────────── */

/** A 3-component vector / point (BCF XYZ triplet). */
export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

/** BCF PerspectiveCamera. */
export interface PerspectiveCamera {
  camera_view_point: Vec3;
  camera_direction: Vec3;
  camera_up_vector: Vec3;
  field_of_view: number;
}

/** BCF OrthogonalCamera. */
export interface OrthogonalCamera {
  camera_view_point: Vec3;
  camera_direction: Vec3;
  camera_up_vector: Vec3;
  view_to_world_scale: number;
}

/* ── Viewpoint ─────────────────────────────────────────────────────────── */

/** Component selection / visibility of a viewpoint. All lists are IFC GUIDs. */
export interface ViewpointComponents {
  selection: string[];
  visible: string[];
  hidden: string[];
  default_visibility: boolean;
}

/** Payload to create a viewpoint. `snapshot_png_b64` is bare base64 (no
 *  data-url prefix). */
export interface ViewpointCreate {
  perspective_camera?: PerspectiveCamera | null;
  orthogonal_camera?: OrthogonalCamera | null;
  components?: ViewpointComponents;
  element_stable_ids?: string[];
  snapshot_png_b64?: string | null;
}

/** A persisted viewpoint. */
export interface Viewpoint {
  guid: string;
  index: number;
  perspective_camera: PerspectiveCamera | null;
  orthogonal_camera: OrthogonalCamera | null;
  components: ViewpointComponents;
  element_stable_ids: string[];
  has_snapshot: boolean;
  snapshot_url: string | null;
}

/* ── Comment ───────────────────────────────────────────────────────────── */

export interface CommentCreate {
  comment: string;
  viewpoint_guid?: string | null;
}

export interface CommentUpdate {
  comment: string;
}

/** A persisted comment. `date` / `modified_date` are ISO-8601 strings. */
export interface BcfComment {
  guid: string;
  comment: string;
  author: string | null;
  date: string | null;
  modified_author: string | null;
  modified_date: string | null;
  viewpoint_guid: string | null;
}

/* ── Topic ─────────────────────────────────────────────────────────────── */

/** Create a BCF topic. Only `title` is required. */
export interface TopicCreate {
  title: string;
  description?: string | null;
  topic_type?: string | null;
  topic_status?: string;
  priority?: string | null;
  stage?: string | null;
  assigned_to?: string | null;
  labels?: string[];
  reference_links?: string[];
  bim_model_id?: string | null;
  due_date?: string | null;
}

/** Patch a BCF topic. Every field optional - only present fields apply. */
export interface TopicUpdate {
  title?: string;
  description?: string | null;
  topic_type?: string | null;
  topic_status?: string | null;
  priority?: string | null;
  stage?: string | null;
  assigned_to?: string | null;
  labels?: string[] | null;
  reference_links?: string[] | null;
  due_date?: string | null;
}

/** A persisted BCF topic with nested comments + viewpoints. */
export interface Topic {
  guid: string;
  project_id: string;
  bim_model_id: string | null;
  title: string;
  description: string | null;
  topic_type: string | null;
  topic_status: string;
  priority: string | null;
  stage: string | null;
  index: number | null;
  assigned_to: string | null;
  due_date: string | null;
  labels: string[];
  reference_links: string[];
  creation_author: string | null;
  creation_date: string | null;
  modified_author: string | null;
  modified_date: string | null;
  comments: BcfComment[];
  viewpoints: Viewpoint[];
}

/* ── Import report (mirror bcf/schemas.py) ─────────────────────────────── */

export interface BcfImportIssue {
  severity: 'error' | 'warning' | 'info';
  code: string;
  message: string;
  location: string | null;
}

export interface BcfImportReport {
  status: 'passed' | 'warnings' | 'errors';
  detected_version: string | null;
  topics_imported: number;
  topics_updated: number;
  comments_imported: number;
  viewpoints_imported: number;
  issues: BcfImportIssue[];
}

/** BCF schema versions the backend can emit / ingest. */
export type BcfVersion = '2.1' | '3.0';

/* ── Topics ────────────────────────────────────────────────────────────── */

/** List BCF topics for a project, newest first. */
export async function listTopics(
  projectId: string,
  opts?: { offset?: number; limit?: number },
): Promise<Topic[]> {
  if (!projectId) return [];
  const params = new URLSearchParams();
  if (opts?.offset != null) params.set('offset', String(opts.offset));
  if (opts?.limit != null) params.set('limit', String(opts.limit));
  const qs = params.toString();
  return apiGet<Topic[]>(
    `/v1/bcf/projects/${enc(projectId)}/topics/${qs ? `?${qs}` : ''}`,
  );
}

/** Fetch one topic with its comments and viewpoints. */
export async function getTopic(projectId: string, topicGuid: string): Promise<Topic> {
  return apiGet<Topic>(
    `/v1/bcf/projects/${enc(projectId)}/topics/${enc(topicGuid)}`,
  );
}

/** Create a new BCF topic. */
export async function createTopic(
  projectId: string,
  body: TopicCreate,
): Promise<Topic> {
  return apiPost<Topic, TopicCreate>(
    `/v1/bcf/projects/${enc(projectId)}/topics/`,
    body,
  );
}

/** Update a topic (backend uses PUT). Only present fields change. */
export async function updateTopic(
  projectId: string,
  topicGuid: string,
  body: TopicUpdate,
): Promise<Topic> {
  return apiPut<Topic, TopicUpdate>(
    `/v1/bcf/projects/${enc(projectId)}/topics/${enc(topicGuid)}`,
    body,
  );
}

/** Delete a topic, its comments, viewpoints and snapshot blobs. */
export async function deleteTopic(projectId: string, topicGuid: string): Promise<void> {
  await apiDelete(`/v1/bcf/projects/${enc(projectId)}/topics/${enc(topicGuid)}`);
}

/* ── Comments ──────────────────────────────────────────────────────────── */

/** Append a comment to a topic (optionally bound to a viewpoint). */
export async function addComment(
  projectId: string,
  topicGuid: string,
  body: CommentCreate,
): Promise<BcfComment> {
  return apiPost<BcfComment, CommentCreate>(
    `/v1/bcf/projects/${enc(projectId)}/topics/${enc(topicGuid)}/comments/`,
    body,
  );
}

/** Edit a comment's text (backend uses PUT). */
export async function updateComment(
  projectId: string,
  topicGuid: string,
  commentGuid: string,
  body: CommentUpdate,
): Promise<BcfComment> {
  return apiPut<BcfComment, CommentUpdate>(
    `/v1/bcf/projects/${enc(projectId)}/topics/${enc(topicGuid)}/comments/${enc(commentGuid)}`,
    body,
  );
}

/** Delete a single comment. */
export async function deleteComment(
  projectId: string,
  topicGuid: string,
  commentGuid: string,
): Promise<void> {
  await apiDelete(
    `/v1/bcf/projects/${enc(projectId)}/topics/${enc(topicGuid)}/comments/${enc(commentGuid)}`,
  );
}

/* ── Viewpoints ────────────────────────────────────────────────────────── */

/** Attach a viewpoint (camera + component selection + optional PNG). */
export async function addViewpoint(
  projectId: string,
  topicGuid: string,
  body: ViewpointCreate,
): Promise<Viewpoint> {
  return apiPost<Viewpoint, ViewpointCreate>(
    `/v1/bcf/projects/${enc(projectId)}/topics/${enc(topicGuid)}/viewpoints/`,
    body,
  );
}

/**
 * Absolute path of a viewpoint snapshot PNG.
 *
 * The endpoint is auth-gated (RequirePermission("bcf.read")), so a plain
 * `<img src>` would 401 - it never carries the Authorization bearer token.
 * Prefer {@link fetchViewpointSnapshotBlob}, which sends the token and yields
 * a blob you can turn into an object URL. This path helper exists for callers
 * that already authenticate the request themselves.
 */
export function viewpointSnapshotPath(
  projectId: string,
  topicGuid: string,
  vpGuid: string,
): string {
  return `${API_BASE}/v1/bcf/projects/${enc(projectId)}/topics/${enc(topicGuid)}/viewpoints/${enc(vpGuid)}/snapshot`;
}

/**
 * Fetch a viewpoint snapshot PNG as a Blob with the Authorization header set.
 *
 * The caller owns the returned blob - wrap it in `URL.createObjectURL` for an
 * `<img>` and `URL.revokeObjectURL` it on unmount.
 */
export async function fetchViewpointSnapshotBlob(
  projectId: string,
  topicGuid: string,
  vpGuid: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const token = getAuthToken();
  const headers: Record<string, string> = { Accept: 'image/png' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(viewpointSnapshotPath(projectId, topicGuid, vpGuid), {
    headers,
    signal,
  });
  if (!resp.ok) {
    throw new Error(`Snapshot fetch failed (HTTP ${resp.status})`);
  }
  return resp.blob();
}

/* ── Export / Import (.bcfzip) ─────────────────────────────────────────── */

/** Extract the filename from a Content-Disposition header, or null. */
function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const raw = match?.[1];
  if (!raw) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

/** Turn a non-2xx fetch Response into a human-readable Error. */
async function errorFromResponse(resp: Response, fallback: string): Promise<Error> {
  let detail = `${fallback} (HTTP ${resp.status})`;
  try {
    const text = await resp.text();
    let body: unknown = text;
    try {
      body = JSON.parse(text);
    } catch {
      /* keep raw text */
    }
    detail = extractErrorMessageFromBody(body) ?? detail;
  } catch {
    /* keep the status fallback */
  }
  return new Error(detail);
}

/**
 * Export every topic of a project as a downloadable `.bcfzip`.
 *
 * Returns the archive blob and the server-suggested filename so the caller can
 * feed both into `triggerDownload`.
 */
export async function exportBcf(
  projectId: string,
  version: BcfVersion = '2.1',
): Promise<{ blob: Blob; filename: string }> {
  const token = getAuthToken();
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(
    `${API_BASE}/v1/bcf/projects/${enc(projectId)}/export?version=${enc(version)}`,
    { headers },
  );
  if (!resp.ok) {
    throw await errorFromResponse(resp, 'BCF export failed');
  }
  const blob = await resp.blob();
  const filename =
    filenameFromDisposition(resp.headers.get('Content-Disposition')) ??
    `project-${projectId}-bcf${version}.bcfzip`;
  return { blob, filename };
}

/**
 * Export a chosen set of topics as a downloadable `.bcfzip`.
 *
 * The companion of {@link exportBcf}: a model review hands the other side
 * exactly the issues it walked, named by BCF GUID. The selection travels in a
 * POST body because a GUID list long enough for a real review would overrun
 * the URL length limits of common reverse proxies.
 *
 * Passing no `topicGuids` exports the whole project (same archive as
 * {@link exportBcf}). A selection that matches nothing is a 422 from the
 * backend, never a hollow archive.
 */
export async function exportBcfSelection(
  projectId: string,
  opts?: { version?: BcfVersion; topicGuids?: string[]; filename?: string },
): Promise<{ blob: Blob; filename: string; topicCount: number | null }> {
  const version = opts?.version ?? '2.1';
  const token = getAuthToken();
  const headers: Record<string, string> = {
    Accept: 'application/octet-stream',
    'Content-Type': 'application/json',
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(`${API_BASE}/v1/bcf/projects/${enc(projectId)}/export`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      version,
      ...(opts?.topicGuids ? { topic_guids: opts.topicGuids } : {}),
    }),
  });
  if (!resp.ok) {
    throw await errorFromResponse(resp, 'BCF export failed');
  }
  const blob = await resp.blob();
  // A missing header must read as "unknown", not as zero. `Number(null)` is 0
  // and passes isFinite, so the absence has to be tested before the cast - the
  // browser hides every response header the server does not expose by name.
  const rawCount = resp.headers.get('X-BCF-Topic-Count');
  const count = rawCount === null || rawCount.trim() === '' ? Number.NaN : Number(rawCount);
  return {
    blob,
    filename:
      opts?.filename ??
      filenameFromDisposition(resp.headers.get('Content-Disposition')) ??
      `project-${projectId}-bcf${version}.bcfzip`,
    topicCount: Number.isFinite(count) ? count : null,
  };
}

/**
 * Import a `.bcfzip`; topics / comments / viewpoints upsert by GUID.
 *
 * A malformed or non-BCF archive returns a structured {@link BcfImportReport}
 * with `status: 'errors'` rather than a 500, so the caller renders the report
 * either way. `version` forces a schema instead of autodetecting.
 */
export async function importBcf(
  projectId: string,
  file: File,
  opts?: { version?: BcfVersion; signal?: AbortSignal },
): Promise<BcfImportReport> {
  const token = getAuthToken();
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const form = new FormData();
  form.append('file', file);
  const params = new URLSearchParams();
  if (opts?.version) params.set('version', opts.version);
  const qs = params.toString();
  const resp = await fetch(
    `${API_BASE}/v1/bcf/projects/${enc(projectId)}/import${qs ? `?${qs}` : ''}`,
    { method: 'POST', headers, body: form, signal: opts?.signal },
  );
  if (!resp.ok) {
    throw await errorFromResponse(resp, 'BCF import failed');
  }
  return resp.json() as Promise<BcfImportReport>;
}
