// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Partner-pack apply / update / un-apply / install client + React Query hooks.
 *
 * Backend: backend/app/core/partner_pack/router.py
 *   GET  /v1/partner-pack/applied            -> AppliedInfo
 *   GET  /v1/partner-pack/apply-preview/{slug} -> ApplyPreview (dry-run)
 *   POST /v1/partner-pack/apply              { slug, confirm_disables }
 *   POST /v1/partner-pack/unapply
 *   POST /v1/partner-pack/rescan
 *   POST /v1/partner-pack/install            multipart: file=<.zip>  (admin)
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, API_BASE, getAuthToken, getErrorMessage } from '@/shared/lib/api';

export interface AppliedInfo {
  applied: boolean;
  source?: 'in-app' | 'env' | null;
  slug?: string | null;
  pack_version?: string;
  applied_at?: string;
  applied_by?: string | null;
  installed?: boolean;
  available_version?: string | null;
  update_available?: boolean;
}

export interface ApplyPlan {
  branding: {
    partner_name: string;
    powered_by: string;
    primary_color: string;
    accent_color?: string | null;
  };
  modules_to_enable: string[];
  modules_to_enable_missing: string[];
  modules_to_disable: string[];
  modules_to_disable_missing: string[];
  default_currency: string;
  default_locale: string;
  additional_locales: string[];
  rule_packs_active: string[];
  rule_packs_documentation_only: string[];
  cwicr_regions: string[];
  default_tax_template?: string | null;
  /** Built-in estimating-methodology slug the pack activates on its demo
   *  project and seeds on projects created while the pack is active. */
  default_methodology?: string | null;
  demo_project?: PackDemoProject | null;
  warnings: string[];
}

export interface PackDemoProject {
  demo_id: string;
  name?: string;
  currency?: string;
  positions?: number;
  region?: string;
  classification_standard?: string;
}

export interface ApplyPreview {
  slug: string;
  partner_name: string;
  pack_version: string;
  will_disable_modules: boolean;
  will_install_demo: boolean;
  plan: ApplyPlan;
}

export interface ApplyResult {
  applied: boolean;
  slug: string;
  pack_version: string;
  effects: {
    modules_enabled: string[];
    modules_disabled: string[];
    modules_failed: { name: string; action: string; error: string }[];
    demo_project?: {
      demo_id: string;
      project_id?: string;
      project_name?: string;
      already_installed: boolean;
    };
    demo_project_failed?: { error: string };
    methodology?: { slug: string; project_id: string };
  };
  skipped_disables: string[];
  warnings: string[];
}

/** Success payload of ``POST /v1/partner-pack/install``. */
export interface InstallResult {
  installed: boolean;
  slug: string;
  partner_name: string;
  pack_version: string;
}

/** Client-side guard limit, mirrors the backend 25 MiB cap so an oversize
 *  upload is rejected before it leaves the browser. */
export const MAX_PACK_UPLOAD_BYTES = 25 * 1024 * 1024;

const KEY_APPLIED = 'partner-pack-applied';
const KEY_INSTALLED = 'partner-packs';

export function useAppliedPack() {
  return useQuery({
    queryKey: [KEY_APPLIED],
    queryFn: () => apiGet<AppliedInfo>('/v1/partner-pack/applied'),
    staleTime: 60_000,
  });
}

export function useApplyPreview(slug: string | null) {
  return useQuery({
    queryKey: ['partner-pack-preview', slug],
    queryFn: () =>
      apiGet<ApplyPreview>(`/v1/partner-pack/apply-preview/${encodeURIComponent(slug as string)}`),
    enabled: Boolean(slug),
    staleTime: 30_000,
  });
}

function useInvalidatePackQueries() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: [KEY_INSTALLED] });
    void qc.invalidateQueries({ queryKey: [KEY_APPLIED] });
    // The whole ['partner-pack'] prefix, which covers both the boot-time
    // co-brand hook ('current') and the header chip ('installed'). Naming one
    // of the two siblings has left the other serving a stale answer.
    void qc.invalidateQueries({ queryKey: ['partner-pack'] });
    void qc.invalidateQueries({ queryKey: ['system-modules'] });
  };
}

export function useApplyPack() {
  const invalidate = useInvalidatePackQueries();
  return useMutation({
    mutationFn: (vars: { slug: string; confirm_disables: boolean; install_demo?: boolean }) =>
      apiPost<ApplyResult>('/v1/partner-pack/apply', vars),
    onSuccess: invalidate,
  });
}

export interface UnapplyResult {
  applied: boolean;
  restored_modules: string[];
  /** Projects released from the pack's scope back into the general workspace. */
  untagged_projects?: number;
}

export function useUnapplyPack() {
  const invalidate = useInvalidatePackQueries();
  return useMutation({
    mutationFn: () => apiPost<UnapplyResult>('/v1/partner-pack/unapply', {}),
    onSuccess: invalidate,
  });
}

export function useRescanPacks() {
  const invalidate = useInvalidatePackQueries();
  return useMutation({
    mutationFn: () => apiPost<{ count: number; slugs: string[] }>('/v1/partner-pack/rescan', {}),
    onSuccess: invalidate,
  });
}

/**
 * Upload a partner-pack ``.zip`` to ``POST /v1/partner-pack/install``.
 *
 * Multipart uploads bypass the JSON ``apiPost`` helper (which always sets a
 * JSON content-type and stringifies the body), so this assembles its own
 * ``FormData`` and ``Authorization`` header via raw ``fetch`` - the same
 * pattern the SSE installer and the project-import upload use. On a non-2xx
 * response the backend returns a user-safe ``{detail}`` string (not a zip /
 * too large / unsafe member / no manifest / slug already installed); we
 * surface that ``detail`` verbatim so the caller can toast it as-is.
 */
export async function installPack(file: File): Promise<InstallResult> {
  const form = new FormData();
  form.append('file', file);

  const token = getAuthToken();
  const response = await fetch(`${API_BASE}/v1/partner-pack/install`, {
    method: 'POST',
    // No explicit Content-Type: the browser sets the multipart boundary.
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });

  if (!response.ok) {
    // Prefer the backend's human-readable ``detail``; fall back to a
    // status-based message via the shared error normaliser.
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // Non-JSON error body (proxy error page, empty 502) — fall through.
    }
    const detail =
      body && typeof body === 'object' && typeof (body as { detail?: unknown }).detail === 'string'
        ? (body as { detail: string }).detail
        : getErrorMessage(body ?? new Error(`HTTP ${response.status}`));
    throw new Error(detail);
  }

  return (await response.json()) as InstallResult;
}

export function useInstallPack() {
  const invalidate = useInvalidatePackQueries();
  return useMutation({
    mutationFn: (file: File) => installPack(file),
    onSuccess: invalidate,
  });
}
