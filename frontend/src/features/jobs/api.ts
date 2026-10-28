// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from '@/shared/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type JobStatus = 'pending' | 'started' | 'success' | 'failure' | 'cancelled';

export interface JobRun {
  id: string;
  kind: string;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result_jsonb: Record<string, unknown> | null;
  error_jsonb: Record<string, unknown> | null;
  progress_pct: number | null;
  progress_message: string | null;
  celery_task_id: string | null;
}

export interface JobListResponse {
  items: JobRun[];
  total: number;
  offset: number;
  limit: number;
}

export interface JobListFilters {
  kind?: string;
  status?: JobStatus;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------------------
// Raw fetchers
// ---------------------------------------------------------------------------

export async function fetchJobs(filters: JobListFilters = {}): Promise<JobListResponse> {
  const params = new URLSearchParams();
  if (filters.kind) params.set('kind', filters.kind);
  if (filters.status) params.set('status', filters.status);
  params.set('limit', String(filters.limit ?? 50));
  params.set('offset', String(filters.offset ?? 0));
  return apiGet<JobListResponse>(`/v1/jobs/?${params}`);
}

export async function fetchJob(id: string): Promise<JobRun> {
  return apiGet<JobRun>(`/v1/jobs/${id}`);
}

export async function cancelJob(id: string): Promise<JobRun> {
  return apiPost<JobRun>(`/v1/jobs/${id}/cancel`);
}

// ---------------------------------------------------------------------------
// React Query hooks
// ---------------------------------------------------------------------------

const JOBS_KEY = ['admin-jobs'];

function jobsQueryKey(filters: JobListFilters) {
  return [...JOBS_KEY, filters];
}

/** Whether the response contains any job that is still running or waiting. */
function hasActiveJobs(data: JobListResponse | undefined): boolean {
  if (!data) return false;
  return data.items.some((j) => j.status === 'pending' || j.status === 'started');
}

export function useJobs(filters: JobListFilters) {
  return useQuery({
    queryKey: jobsQueryKey(filters),
    queryFn: () => fetchJobs(filters),
    // Auto-refresh every 10s when there are active (pending/started) jobs
    refetchInterval: (query) => (hasActiveJobs(query.state.data) ? 10_000 : false),
  });
}

export function useJob(id: string | null) {
  return useQuery({
    queryKey: [...JOBS_KEY, 'detail', id],
    queryFn: () => fetchJob(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === 'pending' || s === 'started' ? 5_000 : false;
    },
  });
}

export function useCancelJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => cancelJob(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: JOBS_KEY });
    },
  });
}
