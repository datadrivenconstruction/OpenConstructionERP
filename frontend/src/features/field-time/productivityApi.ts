// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Foreman productivity report, GET /api/v1/field-time/productivity/.
 * Every figure is a decimal string or null (null = not measurable, never zero).
 */

import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';

export type ProductivityLight = 'green' | 'amber' | 'red' | 'grey';

export interface ProductivityWeek {
  week_start: string;
  labour_hours: string | null;
  quantity?: string | null;
  earned_hours?: string | null;
  productivity_factor: string | null;
}

export interface ProductivityCrew {
  crew_id: string | null;
  crew_name: string;
  labour_hours: string | null;
  share_pct: string | null;
  workers: number;
}

export interface ProductivityRow {
  position_id: string | null;
  cost_code: string;
  ref: string;
  description: string;
  unit: string;
  planned_quantity: string | null;
  installed_quantity: string | null;
  installed_to_date: string | null;
  quantity_source: 'measurement' | 'progress' | null;
  labour_hours: string | null;
  plant_hours: string | null;
  norm_labour_hours_per_unit: string | null;
  norm_plant_hours_per_unit: string | null;
  actual_hours_per_unit: string | null;
  units_per_man_hour: string | null;
  earned_hours: string | null;
  productivity_factor: string | null;
  status: string;
  light: ProductivityLight;
  remaining_quantity: string | null;
  budget_hours_to_complete: string | null;
  forecast_hours_to_complete: string | null;
  forecast_basis: 'to_date_rate' | 'period_rate' | 'norm' | 'none';
  weeks: ProductivityWeek[];
  crews: ProductivityCrew[];
}

export interface ProductivityFinding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info' | string;
  message: string;
  suggestion: string | null;
  element_ref: string | null;
}

export interface ProductivityReport {
  project_id: string;
  date_from: string;
  date_to: string;
  tolerance: string;
  rows: ProductivityRow[];
  totals: {
    labour_hours: string | null;
    plant_hours: string | null;
    earned_hours: string | null;
    spent_hours_with_norm: string | null;
    productivity_factor: string | null;
    status: string;
    light: ProductivityLight;
  };
  weeks: ProductivityWeek[];
  findings: ProductivityFinding[];
}

export function useProductivity(projectId: string, dateFrom: string, dateTo: string) {
  return useQuery({
    queryKey: ['field-time', 'productivity', projectId, dateFrom, dateTo],
    queryFn: () =>
      apiGet<ProductivityReport>(
        `/v1/field-time/productivity/?project_id=${encodeURIComponent(projectId)}&date_from=${dateFrom}&date_to=${dateTo}`,
      ),
    enabled: Boolean(projectId && dateFrom && dateTo && dateFrom <= dateTo),
    retry: false,
  });
}
