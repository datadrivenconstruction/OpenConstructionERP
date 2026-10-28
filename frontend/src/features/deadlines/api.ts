// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet } from '@/shared/lib/api';

export type DeadlineClassification = 'overdue' | 'approaching' | 'on_time';
export type DeadlineSeverity = 'critical' | 'warning' | 'info';
export type DeadlineStatusFilter = 'all' | 'overdue' | 'approaching';

export interface DeadlineItem {
  id: string;
  module: string;
  entity_type: string;
  entity_id: string;
  project_id: string;
  project_name: string | null;
  title: string;
  due_date: string | null;
  owner_user_id: string | null;
  owner_name: string | null;
  status: string;
  classification: DeadlineClassification;
  days_overdue: number;
  severity: DeadlineSeverity;
  action_url: string;
}

export interface DeadlineRegister {
  items: DeadlineItem[];
  overdue_count: number;
  approaching_count: number;
  generated_at: string;
}

/** Fetch the cross-module deadline register for one project. */
export async function fetchDeadlines(params: {
  project_id: string;
  status?: DeadlineStatusFilter;
  module?: string;
}): Promise<DeadlineRegister> {
  const qs = new URLSearchParams({ project_id: params.project_id });
  if (params.status) qs.set('status', params.status);
  if (params.module) qs.set('module', params.module);
  return apiGet<DeadlineRegister>(`/v1/deadlines/?${qs.toString()}`);
}
