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

export function useProjectParties(projectId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ['dataflow', 'parties', projectId ?? null],
    queryFn: () => fetchProjectParties(projectId as string),
    enabled: enabled && !!projectId,
    staleTime: STALE_MS,
  });
}
