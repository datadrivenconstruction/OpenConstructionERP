// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Smart Views — typed API client.
//
// Backed by ``/api/v1/smart-views/`` (mounted by the module loader).
// Every helper goes through ``shared/lib/api.ts``, so JWT auth, 401
// handling, offline cache and i18n locale headers are all free.

import { apiGet, apiPost, apiPut, apiDelete } from '@/shared/lib/api';
import type {
  InstallPresetPayload,
  SmartViewCreatePayload,
  SmartViewEvaluateResponse,
  SmartViewPresetSummary,
  SmartViewResponse,
  SmartViewScopeType,
  SmartViewShareInfo,
  SmartViewUpdatePayload,
} from './types';

const BASE = '/v1/smart-views';

/** ``GET /v1/smart-views/?scope_type=...&scope_id=...`` — list views.
 *
 *  Both query params are optional individually; pass neither to list
 *  every view the caller is allowed to see. The backend already filters
 *  by RBAC visibility — we just narrow the result here. */
export async function listSmartViews(params?: {
  scopeType?: SmartViewScopeType;
  scopeId?: string;
}): Promise<SmartViewResponse[]> {
  const search = new URLSearchParams();
  if (params?.scopeType) search.set('scope_type', params.scopeType);
  if (params?.scopeId) search.set('scope_id', params.scopeId);
  const qs = search.toString();
  const path = qs ? `${BASE}/?${qs}` : `${BASE}/`;
  return apiGet<SmartViewResponse[]>(path);
}

/** ``GET /v1/smart-views/{id}`` — fetch one view. */
export async function getSmartView(viewId: string): Promise<SmartViewResponse> {
  return apiGet<SmartViewResponse>(`${BASE}/${viewId}`);
}

/** ``POST /v1/smart-views/`` — create a new view. */
export async function createSmartView(
  payload: SmartViewCreatePayload,
): Promise<SmartViewResponse> {
  return apiPost<SmartViewResponse, SmartViewCreatePayload>(`${BASE}/`, payload);
}

/** ``PUT /v1/smart-views/{id}`` — partial update of a view.
 *
 *  Note: the scope (``scope_type`` / ``scope_id``) is intentionally NOT
 *  updatable on the backend — it is fixed at creation time. */
export async function updateSmartView(
  viewId: string,
  payload: SmartViewUpdatePayload,
): Promise<SmartViewResponse> {
  return apiPut<SmartViewResponse, SmartViewUpdatePayload>(
    `${BASE}/${viewId}`,
    payload,
  );
}

/** ``DELETE /v1/smart-views/{id}`` — delete a view (authoring user only). */
export async function deleteSmartView(viewId: string): Promise<void> {
  await apiDelete<void>(`${BASE}/${viewId}`);
}

/** ``POST /v1/smart-views/{id}/evaluate?model_id=...`` — evaluate a view
 *  against a specific BIM model and return per-element visual state. */
export async function evaluateSmartView(
  viewId: string,
  modelId: string,
): Promise<SmartViewEvaluateResponse> {
  const path = `${BASE}/${viewId}/evaluate?model_id=${encodeURIComponent(modelId)}`;
  return apiPost<SmartViewEvaluateResponse, undefined>(path, undefined);
}

/** ``GET /v1/smart-views/presets`` — list the built-in preset catalogue.
 *
 *  Static / DB-free on the backend, so it is safe to refetch as often as
 *  the UI wants. Keep the result in React-Query though — the payload is
 *  identical across users and a cached list makes the panel snappy. */
export async function listSmartViewPresets(): Promise<SmartViewPresetSummary[]> {
  return apiGet<SmartViewPresetSummary[]>(`${BASE}/presets`);
}

/** ``POST /v1/smart-views/presets/{preset_id}/install`` — materialise a
 *  preset as a new SmartView under the given scope. */
export async function installSmartViewPreset(
  presetId: string,
  payload: InstallPresetPayload,
): Promise<SmartViewResponse> {
  return apiPost<SmartViewResponse, InstallPresetPayload>(
    `${BASE}/presets/${encodeURIComponent(presetId)}/install`,
    payload,
  );
}

/** ``POST /v1/smart-views/{view_id}/share`` — mint (or rotate) a signed
 *  share token for an owned view. */
export async function createSmartViewShareLink(
  viewId: string,
): Promise<SmartViewShareInfo> {
  return apiPost<SmartViewShareInfo, undefined>(`${BASE}/${viewId}/share`, undefined);
}

/** ``DELETE /v1/smart-views/{view_id}/share`` — revoke the share token. */
export async function revokeSmartViewShareLink(viewId: string): Promise<void> {
  await apiDelete<void>(`${BASE}/${viewId}/share`);
}

/** Compose the full share URL the user copies to their clipboard.
 *
 *  The backend hands us a relative ``/share/smart-views/<token>`` path;
 *  this helper turns it into an absolute URL using
 *  ``window.location.origin`` so the result works in the user's actual
 *  browser context (production, staging, localhost). */
export function buildSmartViewShareUrl(token: string): string {
  const base =
    typeof window !== 'undefined' && window.location?.origin
      ? window.location.origin
      : '';
  return `${base}/smart-views/shared/${token}`;
}

/** ``GET /v1/smart-views/shared/{token}`` — resolve a share token to a view.
 *
 *  dead_button fix: the Share-by-link workflow copied a URL
 *  (``/smart-views/shared/<token>``) that matched no frontend route AND no
 *  page ever called the working *unauthenticated* backend resolver. This is
 *  that missing call — the share-landing page reads ``:token`` from the route
 *  and resolves it here. The path has NO trailing slash so it matches the
 *  backend route exactly under ``redirect_slashes=False`` (router.py:231).
 *  No JWT is required: the signed token IS the auth, so this works for an
 *  anonymous recipient (the whole point of "anyone with the link can view"). */
export async function resolveSmartViewShare(
  token: string,
): Promise<SmartViewResponse> {
  return apiGet<SmartViewResponse>(
    `${BASE}/shared/${encodeURIComponent(token)}`,
  );
}

/** Clone an existing view as a new draft. Mirrors the view's name, rules
 *  and default action; scope_type/scope_id are taken from caller params
 *  so a "Duplicate to project" UX is one call. */
export async function duplicateSmartView(
  source: SmartViewResponse,
  options: {
    scopeType: SmartViewScopeType;
    scopeId: string;
    nameSuffix?: string;
  },
): Promise<SmartViewResponse> {
  const payload: SmartViewCreatePayload = {
    name: `${source.name}${options.nameSuffix ?? ' (copy)'}`,
    description: source.description ?? null,
    folder: source.folder ?? null,
    rules: source.rules.map((r) => ({ ...r })),
    default_action: (source.default_action as 'show_all' | 'hide_all') ?? 'show_all',
    scope_type: options.scopeType,
    scope_id: options.scopeId,
  };
  return createSmartView(payload);
}
