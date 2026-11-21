// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Data paths API: one module's paths, the platform map, the project's parties.

import { useQuery } from '@tanstack/react-query';

import { apiGet } from '@/shared/lib/api';

export type PathState =
  | 'ok'
  | 'stale'
  | 'broken'
  | 'no_access'
  | 'not_installed'
  | 'unknown'
  | 'hidden';

export type Importance = 'critical' | 'high' | 'supporting';

export interface Live {
  count: number | null;
  value: string | null;
  latest_at: string | null;
  state: PathState;
  stale_count: number | null;
  active: boolean;
  reason: string | null;
}

export interface EntityOut {
  id: string;
  model: string;
  label: string;
  route: string;
  measure: string;
  live: Live;
}

export interface PathOut {
  id: string;
  direction: 'in' | 'out';
  module: string;
  entity: string;
  via: string;
  label: string;
  measure: 'count' | 'sum' | 'latest';
  measure_field: string | null;
  route: string;
  importance: Importance;
  breaks: string;
  live: Live;
}

export interface ParamOut {
  field: string;
  label: string;
  drives: string[];
  drives_paths: string[];
}

export interface StaleOut {
  source: string;
  copy_field: string;
  label: string;
  path_id: string | null;
  count: number | null;
}

export interface EdgeOut {
  source: string;
  target: string;
  kind: 'declared' | 'depends' | 'fk' | 'event';
  details: string[];
  importance: Importance;
  label: string;
  count: number | null;
  active: boolean;
  state: PathState;
}

export interface ModulePaths {
  module: string;
  declared: boolean;
  installed: boolean;
  why: string;
  roles: string[];
  project_id: string | null;
  currency: string;
  entities: EntityOut[];
  paths: PathOut[];
  parameters: ParamOut[];
  stale: StaleOut[];
  technical: EdgeOut[];
  neighbours: string[];
  generated_at: string;
}

export interface MapModule {
  name: string;
  display_name: string;
  category: string;
  declared: boolean;
  installed: boolean;
  why: string;
  roles: string[];
  count: number | null;
  counts: Record<string, number>;
}

export interface HealthItem {
  module: string;
  path_id: string;
  source: string;
  label: string;
  importance: Importance;
  breaks: string;
  /** i18n key of the plain sentence for this gap. */
  missing?: string;
  upstream?: string;
  /** Module that has to act; the Fix link opens it. */
  downstream?: string;
}

export interface PlatformMap {
  project_id: string | null;
  currency: string;
  modules: MapModule[];
  edges: EdgeOut[];
  health: HealthItem[];
  generated_at: string;
}

export type PartyZone = 'client' | 'delivery' | 'specialist';

export interface Party {
  id: string;
  kind: 'person' | 'company' | 'organisation' | 'role';
  name: string;
  initials: string;
  zone: PartyZone;
  roles: string[];
  modules: string[];
  placeholder: boolean;
  /** client | contractor | subcontractor | supplier | bidder | consultant | person; empty for placeholders. */
  primary_role?: string;
  /** Records per module that name this party. */
  touches?: Record<string, number>;
  /** Party id of the company a person works for. */
  org?: string | null;
}

export interface ProjectParties {
  project_id: string;
  parties: Party[];
}

const STALE_MS = 60_000;

function withProject(base: string, projectId: string | null | undefined): string {
  return projectId ? `${base}?project_id=${encodeURIComponent(projectId)}` : base;
}

export function fetchModulePaths(module: string, projectId: string | null | undefined): Promise<ModulePaths> {
  return apiGet<ModulePaths>(withProject(`/v1/dataflow/paths/${encodeURIComponent(module)}/`, projectId));
}

export function fetchPlatformMap(projectId: string | null | undefined): Promise<PlatformMap> {
  return apiGet<PlatformMap>(withProject('/v1/dataflow/map/', projectId));
}

export function fetchProjectParties(projectId: string): Promise<ProjectParties> {
  return apiGet<ProjectParties>(`/v1/dataflow/projects/${encodeURIComponent(projectId)}/parties/`);
}

export function useModulePaths(module: string | null, projectId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ['dataflow', 'paths', module, projectId ?? null],
    queryFn: () => fetchModulePaths(module as string, projectId),
    enabled: enabled && !!module,
    staleTime: STALE_MS,
  });
}

export function usePlatformMap(projectId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ['dataflow', 'map', projectId ?? null],
    queryFn: () => fetchPlatformMap(projectId),
    enabled,
    staleTime: STALE_MS,
  });
}

/**
 * The map to draw now, and its live numbers when they land. The project map
 * counts every declared path of every module before it answers, which takes
 * seconds on a real project; the shape of the map does not depend on the
 * project, so it is drawn from the project-less map first and the counts fill
 * in when the project's answer arrives.
 */
export function usePlatformMapProgressive(projectId: string | null | undefined, enabled = true) {
  const shape = usePlatformMap(null, enabled);
  const live = usePlatformMap(projectId, enabled && !!projectId);
  const data = (projectId ? live.data : undefined) ?? shape.data;
  return {
    data,
    isLoading: !data && (shape.isLoading || live.isLoading),
    isError: !data && shape.isError && (!projectId || live.isError),
    countsLoading: !!projectId && !live.data && !live.isError,
  };
}

export interface TraceStep {
  module: string;
  label: string;
  via: string;
}

export interface Trace {
  id: string;
  label: string;
  summary: string;
  steps: TraceStep[];
  /** Step indexes that sit in the focused module. */
  at: number[];
}

export interface ModuleFocus {
  module: string;
  declared: boolean;
  why: string;
  roles: string[];
  duties: { role: string; label: string }[];
  external: { kind: 'party' | 'file' | 'device'; label: string; role: string }[];
  rules: { rule_id: string; name: string; severity: string }[];
  traces: Trace[];
}

export type ChipTone = 'neutral' | 'info' | 'warning' | 'error' | 'success';

export interface Chip {
  id: string;
  label: string;
  count: number;
  tone: ChipTone;
}

export interface ModuleChips {
  module: string;
  chips: Chip[];
  generated_at: string;
}

export interface Change {
  module: string;
  entity: string;
  entity_id: string | null;
  action: string;
  at: string | null;
  user: string;
}

export interface ModuleChanges {
  module: string;
  days: number;
  changes: Change[];
}

/** Live numbers refresh every 30 s while the window is open. */
export const LIVE_REFRESH_MS = 30_000;

export function useModuleFocus(module: string | null, enabled = true) {
  return useQuery({
    queryKey: ['dataflow', 'focus', module],
    queryFn: () => apiGet<ModuleFocus>(`/v1/dataflow/focus/${encodeURIComponent(module as string)}/`),
    enabled: enabled && !!module,
    staleTime: 5 * STALE_MS,
  });
}

/** One request per card, so a failing source hides only its own chips. */
export function useModuleChips(module: string, projectId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ['dataflow', 'chips', module, projectId ?? null],
    queryFn: () => apiGet<ModuleChips>(withProject(`/v1/dataflow/chips/${encodeURIComponent(module)}/`, projectId)),
    enabled: enabled && !!projectId,
    staleTime: LIVE_REFRESH_MS,
    refetchInterval: enabled ? LIVE_REFRESH_MS : false,
    retry: false,
  });
}

export function useModuleChanges(
  module: string | null,
  projectId: string | null | undefined,
  downstream: string[],
  enabled = true,
) {
  const tail = downstream.length ? `&downstream=${encodeURIComponent(downstream.slice(0, 12).join(','))}` : '';
  return useQuery({
    queryKey: ['dataflow', 'changes', module, projectId ?? null, downstream.slice(0, 12).join(',')],
    queryFn: () =>
      apiGet<ModuleChanges>(
        `/v1/dataflow/changes/${encodeURIComponent(module as string)}/?project_id=${encodeURIComponent(projectId as string)}${tail}`,
      ),
    enabled: enabled && !!module && !!projectId,
    staleTime: LIVE_REFRESH_MS,
    refetchInterval: enabled ? LIVE_REFRESH_MS : false,
  });
}

export function useProjectParties(projectId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ['dataflow', 'parties', projectId ?? null],
    queryFn: () => fetchProjectParties(projectId as string),
    enabled: enabled && !!projectId,
    staleTime: STALE_MS,
  });
}
