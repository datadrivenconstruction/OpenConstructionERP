// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Data hook for a standalone model-viewing surface (Model Review).
 *
 * Wraps the same queries BIMPage uses - the project's model list, single-model
 * status polling, and the skeleton element list the 3D viewer matches meshes
 * against - and derives the authenticated geometry URL. Kept separate from
 * BIMPage's large component so a focused review page can mount the shared
 * <BIMViewer> without dragging in the upload / filmstrip / right-panel
 * machinery.
 */

import { useMemo } from 'react';

import { useQuery } from '@tanstack/react-query';

import type { BIMElementData, BIMModelData } from '@/shared/ui/BIMViewer';
import { useAuthStore } from '@/stores/useAuthStore';

import { fetchBIMElements, fetchBIMModel, fetchBIMModels } from './api';

export interface ModelViewerData {
  /** Every model in the project (for the picker). */
  models: BIMModelData[];
  /** The active model, freshened by status polling while it converts. */
  activeModel: BIMModelData | null;
  /** Skeleton element rows the viewer matches meshes to (empty until ready). */
  elements: BIMElementData[];
  /** Authenticated geometry URL, or null when the model has no renderable 3D. */
  geometryUrl: string | null;
  isLoadingModels: boolean;
  isLoadingElements: boolean;
}

/** Load the data a focused viewer page needs for one project + active model. */
export function useModelViewerData(
  projectId: string | null,
  activeModelId: string | null,
): ModelViewerData {
  const modelsQuery = useQuery({
    queryKey: ['bim-models', projectId],
    queryFn: () => fetchBIMModels(projectId!),
    enabled: !!projectId,
  });
  const models = useMemo(() => modelsQuery.data?.items ?? [], [modelsQuery.data]);

  const listedModel = useMemo(
    () => models.find((m) => m.id === activeModelId) ?? null,
    [models, activeModelId],
  );

  // Poll status while the model is still converting so the viewer flips to
  // ready without a manual refresh; idle once it settles.
  const statusQuery = useQuery({
    queryKey: ['bim-model-status', activeModelId],
    queryFn: () => fetchBIMModel(activeModelId!),
    enabled: !!activeModelId && listedModel?.status === 'processing',
    refetchInterval: 4000,
  });
  const activeModel = statusQuery.data ?? listedModel;

  const isRenderable = activeModel?.status === 'ready' || activeModel?.status === 'degraded';

  const elementsQuery = useQuery({
    queryKey: ['bim-elements', activeModelId, 'skeleton'],
    queryFn: () => fetchBIMElements(activeModelId!, { skeleton: true }),
    enabled: !!activeModelId && isRenderable,
  });
  const elements = useMemo(() => elementsQuery.data?.items ?? [], [elementsQuery.data]);

  // Mirror BIMPage's geometry-URL guard exactly: skip the endpoint (which would
  // 404) when the model imported element data but produced no GLB/DAE blob.
  const geometryUrl = useMemo(() => {
    if (
      !activeModelId ||
      !isRenderable ||
      activeModel?.has_geometry === false ||
      ((activeModel?.element_count ?? 0) === 0 && !elements.some((el) => !!el.mesh_ref))
    ) {
      return null;
    }
    const token = useAuthStore.getState().accessToken;
    const base = `/api/v1/bim_hub/models/${encodeURIComponent(activeModelId)}/geometry/`;
    const params = new URLSearchParams();
    if (token) params.set('token', token);
    // Cache-bust on updated_at so re-uploaded geometry is refetched.
    params.set('_t', activeModel?.updated_at || '');
    return `${base}?${params.toString()}`;
  }, [
    activeModelId,
    isRenderable,
    activeModel?.has_geometry,
    activeModel?.element_count,
    activeModel?.updated_at,
    elements,
  ]);

  return {
    models,
    activeModel,
    elements,
    geometryUrl,
    isLoadingModels: modelsQuery.isLoading,
    isLoadingElements: elementsQuery.isLoading,
  };
}
