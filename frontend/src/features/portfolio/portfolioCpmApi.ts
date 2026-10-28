// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed API client for the portfolio / multi-project module (T3.3), mounted by
// the module loader at /api/v1/portfolio.
//
// This is a SEPARATE client from the sibling features/portfolio/api.ts, which
// belongs to the resource capacity-planning / leveling surfaces under
// /v1/resources/portfolio/*. That file owns the name `api.ts`; this one covers
// the enterprise schedule-of-schedules tree and its cross-project CPM, so it is
// named distinctly to avoid clobbering the existing module.
//
// What the backend exposes (see backend/app/modules/portfolio/router.py +
// schemas.py):
//   - GET  /v1/portfolio/tree/                        access-pruned node tree
//   - POST /v1/portfolio/nodes/                       create a node
//   - PATCH /v1/portfolio/nodes/{id}/                 rename / reparent / reorder
//   - DELETE /v1/portfolio/nodes/{id}/                delete a node (projects kept)
//   - POST /v1/portfolio/nodes/{id}/projects/         file a project under a node
//   - DELETE /v1/portfolio/nodes/{id}/projects/{pid}/ remove a project from a node
//   - POST /v1/portfolio/cross-links/                 create a cross-schedule link
//   - GET  /v1/portfolio/cross-links/?schedule_id=    list links touching a schedule
//   - DELETE /v1/portfolio/cross-links/{id}/          delete a cross-link
//   - GET  /v1/portfolio/nodes/{id}/cpm/              portfolio CPM over a subtree
//
// The tree is a navigation / scoping overlay; it never widens project access -
// every read is intersected with the caller's accessible projects server-side.

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

const BASE = '/v1/portfolio';

/** Build a query string from a record, skipping null/undefined/empty values. */
function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue;
    search.append(key, String(value));
  }
  const str = search.toString();
  return str ? `?${str}` : '';
}

// ── Tree ────────────────────────────────────────────────────────────────────

/** A portfolio / programme node kind. */
export type PortfolioNodeType = 'portfolio' | 'programme' | 'subprogramme';

/** A node in the access-pruned portfolio tree (children nested in place). */
export interface PortfolioTreeNode {
  id: string;
  parent_id: string | null;
  node_type: string;
  name: string;
  code: string;
  sort_order: number;
  project_ids: string[];
  children: PortfolioTreeNode[];
}

/** A portfolio node as returned from a write (create / patch). */
export interface PortfolioNode {
  id: string;
  parent_id: string | null;
  node_type: string;
  name: string;
  code: string;
  owner_id: string | null;
  sort_order: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Body for creating a node. */
export interface NodeCreateBody {
  name: string;
  node_type?: PortfolioNodeType;
  code?: string;
  parent_id?: string | null;
  sort_order?: number;
  metadata?: Record<string, unknown>;
}

/**
 * Body for patching a node. Omitting `parent_id` leaves the parent unchanged;
 * passing it as null moves the node to the root (the backend distinguishes the
 * two via the set of supplied fields).
 */
export interface NodePatchBody {
  name?: string;
  node_type?: PortfolioNodeType;
  code?: string;
  parent_id?: string | null;
  sort_order?: number;
}

// ── Cross-schedule links ──────────────────────────────────────────────────────

/** Dependency type carried on a cross-schedule link. */
export type DepType = 'FS' | 'SS' | 'FF' | 'SF';

/** Body for creating a cross-schedule dependency between two activities. */
export interface CrossLinkCreateBody {
  predecessor_schedule_id: string;
  predecessor_activity_id: string;
  successor_schedule_id: string;
  successor_activity_id: string;
  dep_type?: DepType;
  lag_days?: number;
}

/** A cross-schedule dependency as returned from the API.
 *
 *  The `*_name` fields name what the ids point at. The API joins them because
 *  an endpoint can sit in a different schedule, and often a different project,
 *  from the one being listed. A name is null when the schedule or activity has
 *  been deleted out from under a link that outlived it.
 */
export interface CrossLink {
  id: string;
  predecessor_schedule_id: string;
  predecessor_activity_id: string;
  predecessor_schedule_name: string | null;
  predecessor_activity_name: string | null;
  successor_schedule_id: string;
  successor_activity_id: string;
  successor_schedule_name: string | null;
  successor_activity_name: string | null;
  dep_type: string;
  lag_days: number;
  created_at: string;
  updated_at: string;
}

// ── Portfolio (schedule-of-schedules) CPM ─────────────────────────────────────

/** One activity's CPM result on the shared portfolio timeline (work-days). */
export interface PortfolioCpmActivity {
  schedule_id: string;
  activity_id: string;
  schedule_name: string;
  activity_name: string;
  es: number;
  ef: number;
  ls: number;
  lf: number;
  total_float: number;
  is_critical: boolean;
}

/** Portfolio CPM result for a node's subtree. */
export interface PortfolioCpmResult {
  node_id: string;
  schedule_count: number;
  activity_count: number;
  project_finish_workday: number;
  cross_links_applied: number;
  cross_links_omitted: number;
  critical_path: PortfolioCpmActivity[];
  activities: PortfolioCpmActivity[];
}

// ── Client ────────────────────────────────────────────────────────────────────

export const portfolioCpmApi = {
  /** The access-pruned portfolio / programme tree (roots with nested children). */
  getTree: () => apiGet<PortfolioTreeNode[]>(`${BASE}/tree/`),

  /** Create a portfolio / programme node. */
  createNode: (body: NodeCreateBody) => apiPost<PortfolioNode, NodeCreateBody>(`${BASE}/nodes/`, body),

  /** Rename / reparent / reorder a node. */
  patchNode: (nodeId: string, body: NodePatchBody) =>
    apiPatch<PortfolioNode, NodePatchBody>(`${BASE}/nodes/${nodeId}/`, body),

  /** Delete a node. Memberships cascade; the projects themselves are untouched. */
  deleteNode: (nodeId: string) => apiDelete<void>(`${BASE}/nodes/${nodeId}/`),

  /** File a project under a node (the project must be accessible to the caller). */
  attachProject: (nodeId: string, projectId: string) =>
    apiPost<void, { project_id: string }>(`${BASE}/nodes/${nodeId}/projects/`, { project_id: projectId }),

  /** Remove a project from a node (non-destructive). */
  detachProject: (nodeId: string, projectId: string) =>
    apiDelete<void>(`${BASE}/nodes/${nodeId}/projects/${projectId}/`),

  /** Create a cross-schedule dependency (needs access to both projects). */
  createCrossLink: (body: CrossLinkCreateBody) =>
    apiPost<CrossLink, CrossLinkCreateBody>(`${BASE}/cross-links/`, body),

  /** List the cross-links touching a given schedule (as predecessor or successor). */
  listCrossLinks: (scheduleId: string) =>
    apiGet<CrossLink[]>(`${BASE}/cross-links/${qs({ schedule_id: scheduleId })}`),

  /** Delete a cross-link. */
  deleteCrossLink: (linkId: string) => apiDelete<void>(`${BASE}/cross-links/${linkId}/`),

  /** Run the portfolio (schedule-of-schedules) CPM across a node's subtree. */
  nodeCpm: (nodeId: string) => apiGet<PortfolioCpmResult>(`${BASE}/nodes/${nodeId}/cpm/`),
};
