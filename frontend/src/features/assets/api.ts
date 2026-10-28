// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API client for the Asset Operations module (/api/v1/assets).
 *
 * Operational-phase intelligence over the BIM-sourced asset register:
 * portfolio KPIs, health-enriched listing, candidate discovery, warranty
 * alerts, and a per-asset service log. The register data itself is owned
 * by the BIM Hub; this module computes meaning on top of it.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

/* ── Health ─────────────────────────────────────────────────────────────── */

export type WarrantyStatus = 'ok' | 'expiring' | 'expired' | 'unknown';
export type MaintenanceStatus = 'ok' | 'due' | 'overdue' | 'unknown';

export interface AssetHealth {
  warranty_status: WarrantyStatus;
  warranty_until: string | null;
  days_to_warranty_expiry: number | null;
  maintenance_status: MaintenanceStatus;
  next_maintenance_due: string | null;
  days_to_maintenance: number | null;
  maintenance_interval_days: number | null;
  last_serviced: string | null;
  age_days: number | null;
  age_years: number | null;
  service_log_count: number;
  attention_score: number;
  issues: string[];
}

export interface AssetRow {
  id: string;
  model_id: string;
  project_id: string;
  model_name: string;
  stable_id: string;
  element_type: string | null;
  name: string | null;
  storey: string | null;
  manufacturer: string | null;
  model: string | null;
  serial_number: string | null;
  operational_status: string | null;
  parent_system: string | null;
  asset_info: Record<string, unknown>;
  health: AssetHealth;
}

export interface AssetListResponse {
  items: AssetRow[];
  total: number;
  offset: number;
  limit: number;
}

/* ── Portfolio ──────────────────────────────────────────────────────────── */

export interface PortfolioSummary {
  total_assets: number;
  by_operational_status: Record<string, number>;
  by_warranty_status: Record<string, number>;
  by_maintenance_status: Record<string, number>;
  warranties_expiring_soon: number;
  warranties_expired: number;
  maintenance_due: number;
  maintenance_overdue: number;
  needs_attention: number;
  models_covered: number;
  avg_age_years: number | null;
  top_attention: AssetRow[];
}

/* ── Discovery ──────────────────────────────────────────────────────────── */

export interface DiscoveryCandidate {
  id: string;
  model_id: string;
  model_name: string;
  stable_id: string;
  element_type: string | null;
  name: string | null;
  storey: string | null;
  score: number;
  reasons: string[];
  suggested_asset_info: Record<string, string>;
}

export interface DiscoveryResponse {
  items: DiscoveryCandidate[];
  total_candidates: number;
  scanned_elements: number;
  already_tracked: number;
  models_scanned: number;
  threshold: number;
}

/* ── Warranty alerts ────────────────────────────────────────────────────── */

export interface WarrantyAlertItem {
  id: string;
  model_id: string;
  model_name: string;
  stable_id: string;
  name: string | null;
  warranty_until: string | null;
  days_to_expiry: number | null;
  status: 'expired' | 'expiring';
}

export interface WarrantyAlertResponse {
  items: WarrantyAlertItem[];
  total: number;
  dispatched: boolean;
  notifications_sent: number;
  recipients: number;
  notifications_unavailable: boolean;
}

/* ── Service log ────────────────────────────────────────────────────────── */

export interface ServiceLogEntry {
  date: string;
  note: string;
  kind?: string;
  cost?: string | null;
  performed_by?: string | null;
}

export interface ServiceLogResponse {
  asset_id: string;
  service_log: Array<Record<string, unknown>>;
  health: AssetHealth;
}

/* ── Calls ──────────────────────────────────────────────────────────────── */

export async function fetchPortfolio(projectId: string): Promise<PortfolioSummary> {
  return apiGet<PortfolioSummary>(
    `/v1/assets/portfolio?project_id=${encodeURIComponent(projectId)}`,
  );
}

export interface ListAssetsOpts {
  warrantyStatus?: WarrantyStatus;
  maintenanceStatus?: MaintenanceStatus;
  operationalStatus?: string;
  /** Narrow to the same set the portfolio roll-up counts as needing attention. */
  needsAttention?: boolean;
  search?: string;
  sort?: 'attention' | 'name' | 'warranty';
  offset?: number;
  limit?: number;
}

export async function listAssets(
  projectId: string,
  opts: ListAssetsOpts = {},
): Promise<AssetListResponse> {
  const params = new URLSearchParams({ project_id: projectId });
  if (opts.warrantyStatus) params.set('warranty_status', opts.warrantyStatus);
  if (opts.maintenanceStatus) params.set('maintenance_status', opts.maintenanceStatus);
  if (opts.operationalStatus) params.set('operational_status', opts.operationalStatus);
  if (opts.needsAttention) params.set('needs_attention', 'true');
  if (opts.search) params.set('search', opts.search);
  if (opts.sort) params.set('sort', opts.sort);
  params.set('offset', String(opts.offset ?? 0));
  params.set('limit', String(opts.limit ?? 50));
  return apiGet<AssetListResponse>(`/v1/assets/?${params.toString()}`);
}

export async function discoverAssets(
  projectId: string,
  opts: { modelId?: string; threshold?: number; resultLimit?: number } = {},
): Promise<DiscoveryResponse> {
  const params = new URLSearchParams({ project_id: projectId });
  if (opts.modelId) params.set('model_id', opts.modelId);
  if (opts.threshold != null) params.set('threshold', String(opts.threshold));
  if (opts.resultLimit != null) params.set('result_limit', String(opts.resultLimit));
  return apiGet<DiscoveryResponse>(`/v1/assets/discover?${params.toString()}`);
}

export async function scanWarrantyAlerts(
  projectId: string,
  opts: { leadDays?: number; dispatch?: boolean } = {},
): Promise<WarrantyAlertResponse> {
  return apiPost<WarrantyAlertResponse>(
    `/v1/assets/warranty-alerts?project_id=${encodeURIComponent(projectId)}`,
    { lead_days: opts.leadDays ?? 90, dispatch: opts.dispatch ?? false },
  );
}

export async function appendServiceLog(
  elementId: string,
  entry: ServiceLogEntry,
): Promise<ServiceLogResponse> {
  return apiPost<ServiceLogResponse, ServiceLogEntry>(
    `/v1/assets/${encodeURIComponent(elementId)}/service-log`,
    entry,
  );
}
