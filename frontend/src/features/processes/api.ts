// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Background services (processes) - server state.
 *
 * The backend owns the registry of long-running things (AI models, search
 * indexes, schedulers, caches, sync loops) and reports their state; this file
 * only reads it and posts the admin actions. Human names and explanations are
 * keyed by the stable process id in the locales (`processes.items.<id>.*`), with
 * the English text the API sends as the fallback.
 */

import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiGet, apiPost } from '@/shared/lib/api';

export type ProcessCategory = 'ai_model' | 'vector_index' | 'scheduler' | 'cache_warmup' | 'sync' | 'maintenance';

/** `idle` is enabled but not loaded yet: a lazy service loads on first use. */
export type ProcessStatus = 'disabled' | 'idle' | 'starting' | 'running' | 'degraded' | 'error' | 'stopping';

export interface ProcessError {
  message: string;
  at: string | null;
  traceback_id?: string | null;
}

export interface ProcessInfo {
  id: string;
  name_key: string;
  purpose_key: string;
  off_impact_key: string;
  category: ProcessCategory;
  modules: string[];
  start_mode: 'boot' | 'lazy' | 'manual';
  default_enabled: boolean;
  enabled: boolean;
  required: boolean;
  /** False: the service only reports, it has no switch. */
  stoppable: boolean;
  /** True: an environment variable decides, the switch is locked. */
  env_locked: boolean;
  status: ProcessStatus;
  ram_mb_estimate: number;
  ram_mb_actual: number | null;
  last_error: ProcessError | null;
  restart_count: number;
  next_retry_at: string | null;
  started_at: string | null;
  log_tail: string[];
  /** Waiting its turn in the serial start queue: shown as loading. */
  queued?: boolean;
}

export interface ProcessesSnapshot {
  processes: ProcessInfo[];
  total_ram_mb_estimate: number;
  /** Resident memory of the whole server process, when the host can tell. */
  process_rss_mb: number | null;
  first_run_done: boolean;
}

export type ProcessAction = 'enable' | 'disable' | 'restart';

export const CATEGORY_ORDER: ProcessCategory[] = ['ai_model', 'vector_index', 'scheduler', 'cache_warmup', 'sync', 'maintenance'];

export const processesKey = ['processes'] as const;

/** Faster polling while someone is looking at the panel, slow otherwise. */
export const POLL_OPEN_MS = 3000;
export const POLL_IDLE_MS = 30000;

export function fetchProcesses(): Promise<ProcessesSnapshot> {
  return apiGet<ProcessesSnapshot>('/v1/processes/');
}

/** Loading in the background: starting now, or queued to start. */
export function isLoading(p: ProcessInfo): boolean {
  return p.status === 'starting' || (p.queued === true && p.status !== 'running' && p.status !== 'disabled');
}

export function useProcesses(live = false) {
  return useQuery({
    queryKey: processesKey,
    queryFn: fetchProcesses,
    // Fast while someone watches the panel or something is still loading,
    // so the "preparing" note clears as soon as the service is up.
    refetchInterval: (q) =>
      live || (q.state.data?.processes.some(isLoading) ?? false) ? POLL_OPEN_MS : POLL_IDLE_MS,
    staleTime: 2000,
    retry: false,
  });
}

/** The status a row shows between the click and the server confirming it. */
export function pendingStatus(action: ProcessAction): ProcessStatus {
  return action === 'disable' ? 'stopping' : 'starting';
}

export function useProcessAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: ProcessAction }) =>
      apiPost<ProcessInfo>(`/v1/processes/${encodeURIComponent(id)}/${action}`),
    onMutate: async ({ id, action }) => {
      await qc.cancelQueries({ queryKey: processesKey });
      const prev = qc.getQueryData<ProcessesSnapshot>(processesKey);
      if (prev) {
        qc.setQueryData<ProcessesSnapshot>(processesKey, {
          ...prev,
          processes: prev.processes.map((p) =>
            p.id === id ? { ...p, status: pendingStatus(action), enabled: action !== 'disable' } : p,
          ),
        });
      }
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(processesKey, ctx.prev);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: processesKey }),
  });
}

export function useMinimalPreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<ProcessesSnapshot>('/v1/processes/preset', { preset: 'minimal' }),
    onSettled: () => qc.invalidateQueries({ queryKey: processesKey }),
  });
}

export function useFirstRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { module_ids: string[]; start_now: boolean }) =>
      apiPost<ProcessesSnapshot>('/v1/processes/first-run', body),
    onSettled: () => qc.invalidateQueries({ queryKey: processesKey }),
  });
}

export type OverallHealth = 'ok' | 'busy' | 'error' | 'idle';

/** One colour for the header dot: red beats amber beats green; nothing on is grey. */
export function overallHealth(processes: ProcessInfo[]): OverallHealth {
  if (processes.some((p) => p.status === 'error')) return 'error';
  if (processes.some((p) => isLoading(p) || p.status === 'stopping' || p.status === 'degraded')) {
    return 'busy';
  }
  return processes.some(isOn) ? 'ok' : 'idle';
}

export function ramOf(p: ProcessInfo): number {
  return p.ram_mb_actual ?? p.ram_mb_estimate;
}

/** Services a set of modules needs, deduplicated, in registry order. */
export function processesForModules(processes: ProcessInfo[], moduleIds: string[]): ProcessInfo[] {
  const wanted = new Set(moduleIds);
  return processes.filter((p) => p.required || p.modules.some((m) => wanted.has(m)));
}

/**
 * A server without the processes API answers 404, and one that keeps it to
 * administrators answers 403: either way the UI stays out of the way.
 */
export function isUnsupported(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 403);
}

/** Whether the switch and restart can be used at all, whoever is looking. */
export function isControllable(p: ProcessInfo): boolean {
  return p.stoppable && !p.required && !p.env_locked;
}

/** On means doing its job or ready to: running, or enabled and loading on first use. */
export function isOn(p: ProcessInfo): boolean {
  return p.status === 'running' || p.status === 'idle';
}

const ensured = new Set<string>();

/** Test hook: forget which modules were already asked for this session. */
export function resetEnsured(): void {
  ensured.clear();
}

/**
 * Entering a module asks the server to start what it needs, in the background
 * and in turn. Fire and forget: the page never waits for it, and a server
 * without the endpoint is simply not asked again this session.
 */
export function useEnsureModule(moduleId: string): void {
  const qc = useQueryClient();
  useEffect(() => {
    if (ensured.has(moduleId)) return;
    ensured.add(moduleId);
    apiPost(`/v1/processes/ensure?module=${encodeURIComponent(moduleId)}`)
      .then(() => qc.invalidateQueries({ queryKey: processesKey }))
      .catch(() => {
        /* older server or no session: the banner still reads the list */
      });
  }, [moduleId, qc]);
}
