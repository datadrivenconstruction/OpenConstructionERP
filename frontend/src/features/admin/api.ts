// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Audit Log admin page.
 *
 * Wraps the backend `audit_router.py` endpoints (Manager + permission
 * `audit.view`).  The list endpoint supports server-side filtering by
 * user, entity type, action, date range and a basic limit/offset pager.
 *
 * Date filters are passed through verbatim as ISO-8601 strings — the
 * backend currently ignores the date params (older deployments) but the
 * round-trip is intentional so newer backends can apply the filter
 * without a frontend redeploy.
 */

import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';

/** Single audit-log entry as returned by the backend. */
export interface AuditEntry {
  id: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  user_id: string | null;
  ip_address: string | null;
  details: Record<string, unknown> | null;
  created_at: string | null;
}

/** Filters accepted by the list endpoint. All fields optional. */
export interface AuditFilters {
  /** UUID of the user whose actions to filter on. */
  userId?: string | null;
  /** Logical entity name — boq / project / contact / … */
  entityType?: string | null;
  /** Verb — create / update / delete / login / … */
  action?: string | null;
  /** ISO-8601 inclusive lower bound on `created_at`. */
  dateFrom?: string | null;
  /** ISO-8601 inclusive upper bound on `created_at`. */
  dateTo?: string | null;
  /** Sort by `created_at`. Defaults to newest-first server-side. */
  sort?: 'asc' | 'desc' | null;
  /** Page size — backend caps at 200. */
  limit?: number;
  /** Page offset (rows to skip). */
  offset?: number;
}

/**
 * Build the relative URL (path + query string) for the audit list call.
 *
 * Pulled out so unit tests can assert the URL shape without touching
 * `fetch`. Empty / null values are omitted entirely — the backend treats
 * a missing query param the same as "no filter".
 *
 * Note: the backend's user filter is exposed under the awkward alias
 * `user_id_filter` (see `audit_router.py`) — the path param of the
 * `/entity/{id}` route already binds `entity_id`, so the list endpoint
 * needs a distinct query name. We hide that quirk from the caller.
 */
export function buildAuditListUrl(filters: AuditFilters = {}): string {
  const qs = new URLSearchParams();
  if (filters.entityType) qs.set('entity_type', filters.entityType);
  if (filters.action) qs.set('action', filters.action);
  if (filters.userId) qs.set('user_id_filter', filters.userId);
  if (filters.dateFrom) qs.set('date_from', filters.dateFrom);
  if (filters.dateTo) qs.set('date_to', filters.dateTo);
  if (filters.sort) qs.set('sort', filters.sort);
  if (filters.limit != null) qs.set('limit', String(filters.limit));
  if (filters.offset != null) qs.set('offset', String(filters.offset));
  const query = qs.toString();
  return `/v1/audit${query ? `?${query}` : ''}`;
}

/**
 * Build the URL for the `/v1/audit/count` endpoint. The endpoint accepts
 * the same filter set as the list, minus pagination + sort — count is
 * order-independent and not paginated, so we strip those before
 * serialising.
 */
export function buildAuditCountUrl(filters: AuditFilters = {}): string {
  const qs = new URLSearchParams();
  if (filters.entityType) qs.set('entity_type', filters.entityType);
  if (filters.action) qs.set('action', filters.action);
  if (filters.userId) qs.set('user_id_filter', filters.userId);
  if (filters.dateFrom) qs.set('date_from', filters.dateFrom);
  if (filters.dateTo) qs.set('date_to', filters.dateTo);
  const query = qs.toString();
  return `/v1/audit/count${query ? `?${query}` : ''}`;
}

/** Fetch a single page of audit-log entries. */
export async function listAuditEntries(filters: AuditFilters = {}): Promise<AuditEntry[]> {
  return apiGet<AuditEntry[]>(buildAuditListUrl(filters));
}

/**
 * Fetch the total row count for the current filter set. Falls back to
 * ``null`` when the backend doesn't yet ship the `/count` endpoint —
 * the caller treats `null` as "unknown" and hides the X-of-Y label.
 */
export async function countAuditEntries(filters: AuditFilters = {}): Promise<number | null> {
  try {
    const res = await apiGet<{ total: number }>(buildAuditCountUrl(filters));
    return typeof res?.total === 'number' ? res.total : null;
  } catch {
    return null;
  }
}

/** Fetch the audit trail for one specific entity (newest-first). */
export async function getAuditDetail(
  entityType: string,
  entityId: string,
  limit = 50,
  offset = 0,
): Promise<AuditEntry[]> {
  const qs = new URLSearchParams();
  qs.set('limit', String(limit));
  qs.set('offset', String(offset));
  const path = `/v1/audit/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}?${qs.toString()}`;
  return apiGet<AuditEntry[]>(path);
}

/**
 * Well-known entity-type list shown in the module dropdown.
 *
 * Mirrors the verbs audit-emitting modules actually use today. Kept as a
 * stable client-side hint so the dropdown stays useful even when the
 * server hasn't yet surfaced a `/v1/audit/entity-types` endpoint.
 */
export const WELL_KNOWN_ENTITY_TYPES: readonly string[] = [
  'project',
  'boq',
  'position',
  'assembly',
  'cost_item',
  'contact',
  'document',
  'file',
  'rfi',
  'submittal',
  'task',
  'changeorder',
  'variation',
  'invoice',
  'po',
  'tender',
  'bid',
  'inspection',
  'ncr',
  'risk',
  'safety_audit',
  'meeting',
  'transmittal',
  'user',
  'role',
  'module',
] as const;

/** Common verbs across modules — surfaced as a quick-pick for the action filter. */
export const WELL_KNOWN_ACTIONS: readonly string[] = [
  'create',
  'update',
  'delete',
  'login',
  'logout',
  'export',
  'import',
  'enable',
  'disable',
  'approve',
  'reject',
  'status_changed',
  'restore',
  'archive',
] as const;


// ── Permissions Matrix ────────────────────────────────────────────────

/**
 * Canonical role keys exposed by the backend matrix endpoint. Kept as a
 * union (not a generic `string`) so callers using `roles[i]` indexing
 * get autocomplete and the test fixtures stay type-safe.
 *
 * The backend is the source of truth — if a new role is added (or
 * removed) there, this union must follow. Mismatched fallthrough is
 * harmless at runtime (we treat unknown roles as opaque strings).
 */
export type MatrixRole = 'viewer' | 'editor' | 'manager' | 'admin';

/** One permission inside a module group, with its minimum required role. */
export interface MatrixPermission {
  /** Dotted key, e.g. `projects.create`. Used as the row identifier. */
  key: string;
  /** Lowest role that has this permission. Always one of MatrixRole. */
  min_role: MatrixRole;
}

/** A module group inside the matrix payload. */
export interface MatrixModule {
  /** Module identifier, e.g. `projects`, `boq`, `system`. */
  name: string;
  /** All permissions registered under this module. Sorted by key on the server. */
  permissions: MatrixPermission[];
}

/** Top-level payload returned by `GET /v1/admin/permissions/matrix`. */
export interface PermissionsMatrix {
  /** Canonical role order — lowest-privilege first. */
  roles: MatrixRole[];
  /** Numeric level for each role, identical to ROLE_HIERARCHY in the backend. */
  role_hierarchy: Record<string, number>;
  /** Module groups, alphabetically sorted by name. */
  modules: MatrixModule[];
  /** Names of the baseline presets the admin UI can apply. Optional for
   *  older backends that don't yet ship the preset endpoint. */
  presets?: string[];
}

/** Fetch the live RBAC matrix for the admin UI. Requires `audit.view`. */
export async function fetchPermissionsMatrix(): Promise<PermissionsMatrix> {
  return apiGet<PermissionsMatrix>('/v1/admin/permissions/matrix');
}

/** Body for ``PATCH /v1/admin/permissions/{key}``. */
export interface PermissionUpdateBody {
  min_role: MatrixRole;
}

/** Response for ``PATCH /v1/admin/permissions/{key}``. */
export interface PermissionUpdateResponse {
  permission: string;
  previous_min_role: MatrixRole;
  new_min_role: MatrixRole;
}

/** Patch one permission's min_role. Admin-only on the backend; non-admin
 *  callers get a 403 which the page surfaces by falling back to the
 *  read-only matrix. */
export async function updatePermissionMinRole(
  permissionKey: string,
  newMinRole: MatrixRole,
): Promise<PermissionUpdateResponse> {
  return apiPatch<PermissionUpdateResponse, PermissionUpdateBody>(
    `/v1/admin/permissions/${encodeURIComponent(permissionKey)}`,
    { min_role: newMinRole },
  );
}

/** Response for ``POST /v1/admin/permissions/preset/{name}``. */
export interface PresetApplyResponse {
  preset: string;
  permissions_changed: number;
  total_permissions: number;
  changes: { permission: string; previous_min_role: MatrixRole; new_min_role: MatrixRole }[];
}

/** Apply a named baseline preset. Admin-only. */
export async function applyPermissionPreset(
  preset: string,
): Promise<PresetApplyResponse> {
  return apiPost<PresetApplyResponse, Record<string, never>>(
    `/v1/admin/permissions/preset/${encodeURIComponent(preset)}`,
    {},
  );
}

/**
 * Cell semantics for one (role, permission) intersection.
 *
 *   • `allowed`        — role is at or above `min_role`.
 *   • `denied`         — role is below `min_role`.
 *   • `admin-bypass`   — role is admin but min_role > admin would also be
 *                        admin; we never deny admin because the registry
 *                        treats admin as an unconditional bypass. The
 *                        lock icon hints "would otherwise be denied but
 *                        admin gets everything".
 */
export type MatrixCellState = 'allowed' | 'denied' | 'admin-bypass';

/**
 * Pure decision function for one cell in the matrix. Exported so the
 * unit tests can pin the behaviour without spinning up React.
 */
export function cellState(
  role: MatrixRole,
  minRole: MatrixRole,
  hierarchy: Record<string, number>,
): MatrixCellState {
  if (role === 'admin') {
    // Admin always passes the check. If min_role itself is admin, the
    // intersection is still "allowed" — we surface the lock icon only
    // when min_role is *also* admin so the UI can flag "this is admin-
    // only by design", as the brief requests.
    return minRole === 'admin' ? 'admin-bypass' : 'allowed';
  }
  const userLvl = hierarchy[role] ?? -1;
  const minLvl = hierarchy[minRole] ?? Number.POSITIVE_INFINITY;
  return userLvl >= minLvl ? 'allowed' : 'denied';
}
