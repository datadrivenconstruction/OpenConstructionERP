// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * React Query hooks for the Pipeline Builder, bound to the pinned REST
 * contract (built in parallel on the backend — do not deviate). Every read
 * degrades gracefully: a missing optional field at runtime must not crash the
 * UI, so types keep server-owned fields optional and the components default.
 *
 * Uses the shared typed `apiGet/apiPost/apiPut/apiDelete` client.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';

import { apiDelete, apiGet, apiPost, apiPut } from '@/shared/lib/api';

// ── Wire shapes (mirror the pinned contract) ───────────────────────────────

/** Graph JSON persisted on the pipeline (xyflow-friendly). */
export interface PipelineGraphNode {
  id: string;
  type: string;
  params: Record<string, unknown>;
  position: { x: number; y: number };
  /** UI-only: user-renamed title. Carried in params on the wire if backend
   *  doesn't model it; kept here so the editor round-trips it. */
  label?: string;
}

export interface PipelineGraphEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
}

export interface PipelineGraph {
  nodes: PipelineGraphNode[];
  edges: PipelineGraphEdge[];
}

/** Row returned by the list endpoint. */
export interface PipelineSummary {
  id: string;
  name: string;
  description?: string | null;
  is_published?: boolean;
  node_count?: number;
  updated_at?: string;
}

/** Full pipeline. `graph`/`policy` may be absent on a freshly created row. */
export interface Pipeline {
  id: string;
  name: string;
  description?: string | null;
  project_id?: string | null;
  is_published?: boolean;
  graph?: PipelineGraph | null;
  policy?: Record<string, unknown> | null;
  version?: number;
  updated_at?: string;
}

export interface CreatePipelineBody {
  name: string;
  description?: string;
  project_id?: string | null;
  graph: PipelineGraph;
  policy?: Record<string, unknown>;
}

export interface UpdatePipelineBody {
  name?: string;
  description?: string;
  graph?: PipelineGraph;
  policy?: Record<string, unknown>;
  is_published?: boolean;
}

export type RunStatus =
  | 'queued'
  | 'running'
  | 'done'
  | 'success'
  | 'error'
  | 'failed'
  | 'paused'
  | 'cancelled'
  | string;

export interface RunNodeState {
  node_id: string;
  node_type?: string;
  status?: RunStatus;
  output?: unknown;
  error?: string | null;
  took_ms?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface PipelineRunDetail {
  id: string;
  pipeline_id?: string;
  status?: RunStatus;
  progress_percent?: number;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  nodes?: RunNodeState[];
}

export interface PipelineRunSummary {
  id: string;
  status?: RunStatus;
  /** Backend sends an object, e.g. `{ type: 'manual', actor_id: '…' }`. */
  trigger?: { type?: string; [k: string]: unknown };
  started_at?: string | null;
  finished_at?: string | null;
  progress_percent?: number;
}

export interface StartRunResponse {
  run_id: string;
  job_run_id?: string;
  status?: RunStatus;
}

/** A node type advertised by the backend node-type catalogue. */
export interface NodeTypeDef {
  type: string;
  category: string;
  label?: string;
  description?: string;
  module?: string;
  /**
   * Input ports. `required` marks a port that must be wired before the node
   * can run; when the backend omits it, the linter treats the port as required
   * only when it is the node's sole input (see {@link requiredInputIds}).
   */
  inputs?: Array<{ id: string; label?: string; type?: string; required?: boolean }>;
  outputs?: Array<{ id: string; label?: string; type?: string }>;
  params_schema?: Record<string, unknown>;
  side_effecting?: boolean;
}

/**
 * The set of input-port ids a node-type *requires* to be wired before it can
 * run. Derived from the catalogue (the linter's authoring-issue heuristic):
 *   1. ports explicitly flagged `required: true` win;
 *   2. otherwise, when no port is explicitly flagged, a single-input node
 *      needs that one port wired (a lone input is the data the step consumes),
 *      while a multi-input node is treated as "any one input is enough" so we
 *      don't flag steps that legitimately read from params instead of a wire.
 */
export function requiredInputIds(def: NodeTypeDef | undefined): string[] {
  const inputs = def?.inputs ?? [];
  if (inputs.length === 0) return [];
  const explicit = inputs.filter((p) => p.required).map((p) => p.id);
  if (explicit.length > 0) return explicit;
  const sole = inputs.length === 1 ? inputs[0] : undefined;
  return sole ? [sole.id] : [];
}

// ── Query keys ─────────────────────────────────────────────────────────────

export const pipelineKeys = {
  all: ['pipelines'] as const,
  list: (projectId?: string | null) => ['pipelines', 'list', projectId ?? null] as const,
  detail: (id: string) => ['pipelines', 'detail', id] as const,
  nodeTypes: ['pipelines', 'node-types'] as const,
  runs: (id: string) => ['pipelines', 'runs', id] as const,
  run: (runId: string) => ['pipelines', 'run', runId] as const,
};

// ── Helpers ────────────────────────────────────────────────────────────────

/** A run is finished once it reaches a terminal status. */
export function isTerminalRunStatus(status?: RunStatus): boolean {
  return (
    status === 'done' ||
    status === 'success' ||
    status === 'error' ||
    status === 'failed' ||
    status === 'cancelled'
  );
}

// ── Hooks ──────────────────────────────────────────────────────────────────

/** List pipelines, optionally scoped to a project. */
export function usePipelineList(
  projectId?: string | null,
): UseQueryResult<PipelineSummary[]> {
  return useQuery({
    queryKey: pipelineKeys.list(projectId),
    queryFn: async () => {
      const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
      const data = await apiGet<PipelineSummary[]>(`/v1/pipelines/${qs}`);
      return Array.isArray(data) ? data : [];
    },
  });
}

/** Fetch one pipeline (graph + policy + meta). */
export function usePipeline(id: string | undefined): UseQueryResult<Pipeline> {
  return useQuery({
    queryKey: pipelineKeys.detail(id ?? ''),
    enabled: Boolean(id),
    queryFn: () => apiGet<Pipeline>(`/v1/pipelines/${id}`),
  });
}

/** The node-type catalogue that populates the palette + inspector forms. */
export function useNodeTypes(): UseQueryResult<NodeTypeDef[]> {
  return useQuery({
    queryKey: pipelineKeys.nodeTypes,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const data = await apiGet<NodeTypeDef[]>('/v1/pipelines/node-types/');
      return Array.isArray(data) ? data : [];
    },
  });
}

export function useCreatePipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreatePipelineBody) =>
      apiPost<Pipeline, CreatePipelineBody>('/v1/pipelines/', body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: pipelineKeys.all });
    },
  });
}

export function useUpdatePipeline(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: UpdatePipelineBody) =>
      apiPut<Pipeline, UpdatePipelineBody>(`/v1/pipelines/${id}`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: pipelineKeys.detail(id) });
      void qc.invalidateQueries({ queryKey: pipelineKeys.all });
    },
  });
}

export function useDeletePipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete<void>(`/v1/pipelines/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: pipelineKeys.all });
    },
  });
}

export function useRunPipeline(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiPost<StartRunResponse, Record<string, never>>(
        `/v1/pipelines/${id}/run`,
        {},
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: pipelineKeys.runs(id) });
    },
  });
}

/** Run history for a pipeline (reverse-chronological list rendered as-is). */
export function usePipelineRuns(
  id: string | undefined,
  enabled = true,
): UseQueryResult<PipelineRunSummary[]> {
  return useQuery({
    queryKey: pipelineKeys.runs(id ?? ''),
    enabled: Boolean(id) && enabled,
    queryFn: async () => {
      const data = await apiGet<PipelineRunSummary[]>(`/v1/pipelines/${id}/runs/`);
      return Array.isArray(data) ? data : [];
    },
  });
}

/**
 * Poll a single run's detail while it is live. Polling stops automatically
 * once the run reaches a terminal status (no websocket — polling by design).
 *
 * Resilience: polling pauses while the query is in an error state (backend
 * unreachable / 4xx-5xx) so a flapping backend can't spin the poller forever,
 * and bounded retries keep a transient blip from looking like a hang.
 */
export function usePipelineRun(
  runId: string | undefined,
): UseQueryResult<PipelineRunDetail> {
  return useQuery({
    queryKey: pipelineKeys.run(runId ?? ''),
    enabled: Boolean(runId),
    retry: 3,
    refetchInterval: (query) => {
      // Pause polling once the query has errored — refetchIntervalPausedFilter
      // resumes it after a successful refetch, so a recovered backend picks the
      // poll back up without leaving it spinning during the outage.
      if (query.state.status === 'error') return false;
      const data = query.state.data as PipelineRunDetail | undefined;
      if (!data) return 1500;
      return isTerminalRunStatus(data.status) ? false : 1500;
    },
    queryFn: () => apiGet<PipelineRunDetail>(`/v1/pipelines/runs/${runId}`),
  });
}
