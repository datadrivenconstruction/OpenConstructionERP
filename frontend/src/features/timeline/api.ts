// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { apiGet } from '@/shared/lib/api';

export interface TimelineEntry {
  id: string;
  entity_type: string;
  entity_id: string | null;
  action: string;
  module: string | null;
  from_status: string | null;
  to_status: string | null;
  parent_entity_type: string | null;
  parent_entity_id: string | null;
  actor_id: string | null;
  reason: string | null;
  metadata: Record<string, unknown>;
  created_at: string | null;
}

export interface TimelineResponse {
  entries: TimelineEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface TimelineFilters {
  module?: string[];
  action?: string[];
  entity_type?: string;
  actor?: string;
  since?: string;
  until?: string;
}

export async function fetchProjectTimeline(
  projectId: string,
  filters: TimelineFilters = {},
  limit = 100,
  offset = 0,
): Promise<TimelineResponse> {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  if (filters.module) filters.module.forEach((m) => params.append('module', m));
  if (filters.action) filters.action.forEach((a) => params.append('action', a));
  if (filters.entity_type) params.set('entity_type', filters.entity_type);
  if (filters.actor) params.set('actor', filters.actor);
  if (filters.since) params.set('since', filters.since);
  if (filters.until) params.set('until', filters.until);
  return apiGet<TimelineResponse>(`/v1/timeline/projects/${projectId}?${params}`);
}
