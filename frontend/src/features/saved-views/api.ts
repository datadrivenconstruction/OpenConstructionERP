// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ShareScope = 'private' | 'team' | 'project' | 'workspace';

export interface SavedView {
  id: string;
  owner_id: string;
  project_id: string | null;
  entity_type: string;
  name: string;
  description: string | null;
  spec: Record<string, unknown>;
  share_scope: ShareScope;
  shared_team_id: string | null;
  is_pinned: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  is_stale: boolean;
  stale_reasons: string[];
}

export interface SavedViewCreate {
  entity_type: string;
  name: string;
  description?: string | null;
  spec?: Record<string, unknown>;
  share_scope?: ShareScope;
  shared_team_id?: string | null;
  is_pinned?: boolean;
  project_id: string;
  metadata?: Record<string, unknown>;
}

export interface SavedViewUpdate {
  name?: string;
  description?: string | null;
  spec?: Record<string, unknown>;
  share_scope?: ShareScope;
  shared_team_id?: string | null;
  is_pinned?: boolean;
  metadata?: Record<string, unknown>;
}

export interface EntityInfo {
  default_sort: string[];
  default_columns: string[];
  max_rows: number;
  fields: EntityField[];
}

export interface EntityField {
  name: string;
  kind: string;
  filterable: boolean;
  sortable: boolean;
  selectable: boolean;
  groupable: boolean;
  enum_values: string[] | null;
}

// ---------------------------------------------------------------------------
// Raw fetchers
// ---------------------------------------------------------------------------

export async function fetchSavedViews(
  projectId?: string,
  entityType?: string,
): Promise<SavedView[]> {
  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  if (entityType) params.set('entity_type', entityType);
  return apiGet<SavedView[]>(`/v1/saved-views/?${params}`);
}

export async function fetchSavedView(id: string, projectId?: string): Promise<SavedView> {
  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  return apiGet<SavedView>(`/v1/saved-views/${id}?${params}`);
}

export async function fetchEntities(): Promise<{ entities: Record<string, EntityInfo> }> {
  return apiGet<{ entities: Record<string, EntityInfo> }>('/v1/saved-views/entities');
}

export async function createSavedView(payload: SavedViewCreate): Promise<SavedView> {
  return apiPost<SavedView>('/v1/saved-views/', payload);
}

export async function updateSavedView(id: string, payload: SavedViewUpdate): Promise<SavedView> {
  return apiPatch<SavedView>(`/v1/saved-views/${id}`, payload);
}

export async function deleteSavedView(id: string, projectId?: string): Promise<void> {
  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  return apiDelete(`/v1/saved-views/${id}?${params}`);
}

// ---------------------------------------------------------------------------
// React Query hooks
// ---------------------------------------------------------------------------

const VIEWS_KEY = ['saved-views'];

export function useSavedViews(projectId?: string, entityType?: string) {
  return useQuery({
    queryKey: [...VIEWS_KEY, projectId, entityType],
    queryFn: () => fetchSavedViews(projectId, entityType),
    enabled: !!projectId,
  });
}

export function useSavedView(id: string | null, projectId?: string) {
  return useQuery({
    queryKey: [...VIEWS_KEY, 'detail', id],
    queryFn: () => fetchSavedView(id!, projectId),
    enabled: !!id,
  });
}

export function useEntities() {
  return useQuery({
    queryKey: [...VIEWS_KEY, 'entities'],
    queryFn: fetchEntities,
    staleTime: 5 * 60_000,
  });
}

export function useCreateSavedView() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: SavedViewCreate) => createSavedView(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: VIEWS_KEY });
    },
  });
}

export function useUpdateSavedView() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: SavedViewUpdate }) =>
      updateSavedView(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: VIEWS_KEY });
    },
  });
}

export function useDeleteSavedView() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, projectId }: { id: string; projectId?: string }) =>
      deleteSavedView(id, projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: VIEWS_KEY });
    },
  });
}
