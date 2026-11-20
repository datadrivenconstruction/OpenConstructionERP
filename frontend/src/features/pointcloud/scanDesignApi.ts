// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Scan against design: deviation reports, their heatmap points and exports,
 * and cut/fill from a scan into a draft survey volume.
 */
import { apiGet, apiPost } from '@/shared/lib/api';
import type { Finding } from '@/features/survey/volumesApi';

export type DeviationBand = 'far_low' | 'low' | 'within' | 'high' | 'far_high' | 'none';

export interface DeviationStats {
  points_read: number;
  points_compared: number;
  points_outside: number;
  tolerance_mm: number;
  mean_mm: number | null;
  rms_mm: number | null;
  std_mm: number | null;
  p95_mm: number | null;
  min_mm: number | null;
  max_mm: number | null;
  within_pct: number | null;
  high_pct: number | null;
  low_pct: number | null;
  out_count: number;
  coverage_pct: number;
  bands: Record<DeviationBand, number>;
}

export interface DeviationReport {
  id: string;
  scan_id: string;
  project_id: string;
  surface_id: string;
  surface_code: string;
  surface_name: string;
  tolerance: { key: string; label: string; source: string; item_type: string; v_mm: number; reference: string };
  threshold_pct: number;
  ground_only: boolean;
  used_all_classes: boolean;
  stats: DeviationStats;
  severity: 'within' | 'warning' | 'over' | 'unknown' | string;
  findings: Finding[];
  created_at: string | null;
}

export interface DeviationInput {
  surface_id: string;
  tolerance_key: string;
  item_type?: string;
  ground_only: boolean;
  threshold_pct: number;
}

export interface CutFillInput {
  surface_id: string;
  cell_size_m: number;
  stat: 'min' | 'mean' | 'max';
  ground_only: boolean;
  method: 'grid' | 'tin';
  name?: string;
}

export interface CutFillPreview {
  surface_id: string;
  surface_name: string;
  method: string;
  cell_size_m: number;
  cut_m3: number;
  fill_m3: number;
  net_m3: number;
  coverage_pct: number;
  points_read: number;
  cells: number;
  used_all_classes: boolean;
}

export interface CutFillCreated {
  scan_surface_id: string;
  scan_surface_code: string;
  volume_id: string;
  volume_code: string;
  status: string;
  cut_m3: number;
  fill_m3: number;
  net_m3: number;
  coverage_pct: number;
  findings: Finding[];
}

const q = (locale: string) => `?locale=${encodeURIComponent(locale)}`;

export const listDeviationReports = (scanId: string, locale: string) =>
  apiGet<{ items: DeviationReport[]; total: number }>(`/v1/pointcloud/scans/${scanId}/deviation-reports${q(locale)}`).then((r) => r.items);

export const runDeviation = (scanId: string, body: DeviationInput, locale: string) =>
  apiPost<DeviationReport>(`/v1/pointcloud/scans/${scanId}/deviation-reports${q(locale)}`, body);

export const previewCutFill = (scanId: string, body: CutFillInput) =>
  apiPost<CutFillPreview>(`/v1/pointcloud/scans/${scanId}/cutfill/preview`, body);

export const createCutFill = (scanId: string, body: CutFillInput, locale: string) =>
  apiPost<CutFillCreated>(`/v1/pointcloud/scans/${scanId}/cutfill${q(locale)}`, body);

/** OEPC source for the viewer: the report's points coloured by deviation band. */
export const deviationPointsPath = (reportId: string) => `/v1/pointcloud/deviation-reports/${reportId}/points`;

export const deviationExportUrl = (reportId: string, format: 'pdf' | 'csv', locale: string) =>
  `/api/v1/pointcloud/deviation-reports/${reportId}/export?format=${format}&locale=${encodeURIComponent(locale)}`;
