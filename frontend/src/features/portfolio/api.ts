// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet } from '@/shared/lib/api';

export interface PortfolioBucket {
  index: number;
  start: string;
  end: string;
  label: string;
}

export interface PortfolioCellProject {
  project_id: string | null;
  project_name: string;
  allocation_percent: number;
}

export interface PortfolioCell {
  bucket_index: number;
  allocation_percent: number;
  over_allocated: boolean;
  cross_project: boolean;
  projects: PortfolioCellProject[];
}

export interface PortfolioResourceRow {
  resource_id: string;
  code: string;
  name: string;
  resource_type: string;
  is_floating: boolean;
  peak_allocation_percent: number;
  has_conflict: boolean;
  cells: PortfolioCell[];
}

export interface PortfolioCapacityResponse {
  start: string;
  end: string;
  bucket: string;
  buckets: PortfolioBucket[];
  resources: PortfolioResourceRow[];
  total_resources: number;
  floating_resources: number;
  conflict_resources: number;
}

// ── Portfolio resource leveling ───────────────────────────────────────────

export interface LevelingBooking {
  assignment_id: string;
  project_id: string | null;
  project_name: string;
  allocation_percent: number;
  status: string;
  start_at: string;
  end_at: string;
}

export interface LevelingSuggestion {
  action: 'shift' | 'spread' | string;
  bucket_index: number;
  target_assignment_id: string;
  target_project_id: string | null;
  target_project_name: string;
  overflow_percent: number;
  suggested_allocation_percent: number;
  rationale: string;
}

export interface LevelingCell {
  bucket_index: number;
  allocation_percent: number;
  capacity_percent: number | null;
  over_allocated: boolean;
  capacity_unknown: boolean;
  cross_project: boolean;
  bookings: LevelingBooking[];
}

export interface LevelingResourceRow {
  resource_id: string;
  code: string;
  name: string;
  resource_type: string;
  is_floating: boolean;
  capacity_percent: number | null;
  capacity_unknown: boolean;
  peak_allocation_percent: number;
  overload_bucket_count: number;
  has_overload: boolean;
  cells: LevelingCell[];
  suggestions: LevelingSuggestion[];
}

export interface PortfolioLevelingResponse {
  start: string;
  end: string;
  bucket: string;
  project_id: string | null;
  buckets: PortfolioBucket[];
  resources: LevelingResourceRow[];
  total_resources: number;
  overloaded_resources: number;
  capacity_unknown_resources: number;
  total_suggestions: number;
}

export const portfolioApi = {
  /** Org-wide resource utilization heatmap across every project. */
  getCapacity: (params: { start: string; end: string; bucket: 'week' | 'month' }) =>
    apiGet<PortfolioCapacityResponse>(
      `/v1/resources/portfolio/capacity?start=${encodeURIComponent(params.start)}&end=${encodeURIComponent(params.end)}&bucket=${params.bucket}`,
    ),

  /**
   * Read-only portfolio resource-leveling grid: per resource x period
   * allocation totals with overload flags (against the resource's declared
   * capacity) and leveling suggestions. Nothing is moved server-side.
   */
  getLeveling: (params: {
    start: string;
    end: string;
    bucket: 'week' | 'month';
    projectId?: string;
  }) =>
    apiGet<PortfolioLevelingResponse>(
      `/v1/resources/portfolio/leveling?start=${encodeURIComponent(params.start)}&end=${encodeURIComponent(params.end)}&bucket=${params.bucket}${
        params.projectId ? `&project_id=${encodeURIComponent(params.projectId)}` : ''
      }`,
    ),
};
