// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the engineering brief screens.

import { useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchDocuments } from '@/features/documents/api';

import {
  briefErrorCode,
  briefKeys,
  getBrief,
  getPinnedCatalogue,
  getSpecification,
  listBriefFindings,
  listCatalogues,
  listConcepts,
  listGates,
  listMilestones,
  listProgramme,
  listRequirements,
  listStudies,
} from './api';

/** The brief, or null when the project has none yet (404 `brief_missing`), which is an empty state and not an error. */
export function useBrief(projectId: string) {
  return useQuery({
    queryKey: briefKeys.brief(projectId),
    queryFn: async () => {
      try {
        return await getBrief(projectId);
      } catch (err) {
        // Only `brief_missing` is the empty state: a bare 404 also means the project is not visible.
        if (briefErrorCode(err) === 'brief_missing') return null;
        throw err;
      }
    },
    enabled: !!projectId,
    retry: false,
  });
}

export function useBriefCatalogues(enabled = true) {
  return useQuery({
    queryKey: briefKeys.catalogues,
    queryFn: () => listCatalogues().then((page) => page.items),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function usePinnedCatalogue(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: briefKeys.catalogue(projectId),
    queryFn: () => getPinnedCatalogue(projectId),
    enabled: enabled && !!projectId,
    retry: false,
  });
}

export function useBriefFindings(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: briefKeys.findings(projectId),
    queryFn: () => listBriefFindings(projectId).then((page) => page.items),
    enabled: enabled && !!projectId,
    retry: false,
  });
}

export function useRequirements(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: briefKeys.requirements(projectId),
    queryFn: () => listRequirements(projectId).then((page) => page.items),
    enabled: enabled && !!projectId,
    retry: false,
  });
}

export function useConcepts(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: briefKeys.concept(projectId),
    queryFn: () => listConcepts(projectId).then((page) => page.items),
    enabled: enabled && !!projectId,
    retry: false,
  });
}

export function useProgramme(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: briefKeys.programme(projectId),
    queryFn: () => listProgramme(projectId).then((page) => page.items),
    enabled: enabled && !!projectId,
    retry: false,
  });
}

export function useGates(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['engineering_brief', projectId, 'gates'],
    queryFn: () => listGates(projectId).then((page) => page.items),
    enabled: enabled && !!projectId,
    retry: false,
  });
}

export function useMilestones(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: briefKeys.milestones(projectId),
    queryFn: () => listMilestones(projectId).then((page) => page.items),
    enabled: enabled && !!projectId,
    retry: false,
  });
}

export function useStudies(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: briefKeys.studies(projectId),
    queryFn: () => listStudies(projectId).then((page) => page.items),
    enabled: enabled && !!projectId,
    retry: false,
  });
}

export function useSpecification(projectId: string, enabled: boolean) {
  return useQuery({
    queryKey: briefKeys.specification(projectId),
    queryFn: () => getSpecification(projectId),
    enabled: enabled && !!projectId,
    retry: false,
  });
}

/**
 * One page of the project's documents as a pick list, searched on the server. The study
 * report and the issued specification live there. `total` tells the picker whether more
 * pages exist behind the rows it holds.
 */
export function useProjectDocuments(projectId: string, enabled: boolean, search = '', limit = 50) {
  return useQuery({
    queryKey: ['engineering-brief', projectId, 'documents', search, limit],
    queryFn: () => fetchDocuments(projectId, { search: search.trim(), limit }),
    enabled: enabled && !!projectId,
    retry: false,
    placeholderData: (previous) => previous,
  });
}

/** After any write: every query of the project is stale, because findings and statuses cross the tabs. */
export function useInvalidateBrief(projectId: string) {
  const qc = useQueryClient();
  return useCallback(() => qc.invalidateQueries({ queryKey: briefKeys.project(projectId) }), [qc, projectId]);
}
