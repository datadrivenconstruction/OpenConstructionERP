// Design module (ERP side of the design editor link).
import { apiGet, apiPost } from '@/shared/lib/api';
import type { ScheduleImpact } from './data/schedule';

/** What accepting the revision would do to the design schedule. Writes nothing. */
export function fetchScheduleImpact(revisionId: string): Promise<ScheduleImpact> {
  return apiGet<ScheduleImpact>(`/v1/design/revisions/${revisionId}/schedule-impact`);
}

/** Create the design schedule of a project (a project manager's act). */
export function setupSchedule(projectId: string): Promise<{ schedule: boolean }> {
  return apiPost<{ schedule: boolean }, Record<string, never>>(`/v1/design/projects/${projectId}/schedule/setup`, {});
}
