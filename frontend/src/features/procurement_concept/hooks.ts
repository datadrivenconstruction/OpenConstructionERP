// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the procurement concept screens, plus the two pieces
// every screen needs: how to name a catalogue item in the reader's language,
// and how to turn a refused request into the sentence the server gave.

import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import {
  getConcept,
  getLedger,
  getPinnedCatalogue,
  getSchedule,
  getThreshold,
  listCandidates,
  listCatalogues,
  listFindings,
  listAdvanceReleases,
  listCostSections,
  listFrameworks,
  getPermitLotRequirements,
  listGates,
  listProjectFrameworks,
  listTenderPackages,
  listPackages,
  listProfiles,
  listRuleSnapshots,
  listSoundings,
  procurementErrorCode,
  procurementErrorMessage,
  procurementKeys,
} from './api';
import { errorText, type LabelContext, type TFn } from './labels';

/** The concept, or null when the project has none yet (404 `concept_missing`), which is an empty state and not an error. */
export function useConcept(projectId: string) {
  return useQuery({
    queryKey: procurementKeys.concept(projectId),
    queryFn: async () => {
      try {
        return await getConcept(projectId);
      } catch (err) {
        // Only `concept_missing` is the empty state. A bare 404 also means the
        // project is not visible to this user, and that must read as an error.
        if (procurementErrorCode(err) === 'concept_missing') return null;
        throw err;
      }
    },
    enabled: !!projectId,
    retry: false,
  });
}

export function useCatalogues(enabled = true) {
  return useQuery({
    queryKey: procurementKeys.catalogues,
    queryFn: () => listCatalogues().then((p) => p.items),
    enabled,
  });
}

export function usePinnedCatalogue(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.catalogue(projectId),
    queryFn: () => getPinnedCatalogue(projectId),
    enabled: !!projectId && enabled,
    staleTime: 60_000,
  });
}

export function useFindings(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.findings(projectId),
    queryFn: () => listFindings(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function usePackages(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.packages(projectId),
    queryFn: () => listPackages(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useThreshold(projectId: string, packageId: string | null) {
  return useQuery({
    queryKey: procurementKeys.threshold(projectId, packageId ?? ''),
    queryFn: () => getThreshold(projectId, packageId as string),
    enabled: !!projectId && !!packageId,
  });
}

export function useRuleSnapshots(projectId: string, packageId: string | null) {
  return useQuery({
    queryKey: procurementKeys.ruleSnapshots(projectId, packageId ?? ''),
    queryFn: () => listRuleSnapshots(projectId, packageId as string),
    enabled: !!projectId && !!packageId,
  });
}

export function useProfiles(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.profiles(projectId),
    queryFn: () => listProfiles(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useCandidates(projectId: string, packageId: string | null) {
  return useQuery({
    queryKey: procurementKeys.candidates(projectId, packageId ?? ''),
    queryFn: () => listCandidates(projectId, packageId as string),
    enabled: !!projectId && !!packageId,
  });
}

export function useSoundings(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.soundings(projectId),
    queryFn: () => listSoundings(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useSchedule(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.schedule(projectId),
    queryFn: () => getSchedule(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useFrameworks(enabled = true) {
  return useQuery({
    queryKey: procurementKeys.frameworks,
    queryFn: () => listFrameworks(),
    enabled,
  });
}

/** The agreements a package of this project may call off. */
export function useProjectFrameworks(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.projectFrameworks(projectId),
    queryFn: () => listProjectFrameworks(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

/** The gates of the project, for naming the one that releases procurement. */
export function useGates(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.gates(projectId),
    queryFn: () => listGates(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

/** The acts of the release gate that can release an advance package. */
export function useAdvanceReleases(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.advanceReleases(projectId),
    // The whole answer: besides the items it says whether released commitments could be read.
    queryFn: () => listAdvanceReleases(projectId),
    enabled: !!projectId && enabled,
  });
}

/** The bill of quantities sections a package can take its scope lines from. */
export function useCostSections(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.costSections(projectId),
    queryFn: () => listCostSections(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

/** The tender packages of the project an award package can be linked to. */
export function useTenderPackages(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.tenderPackages(projectId),
    queryFn: () => listTenderPackages(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useLedger(frameworkId: string | null) {
  return useQuery({
    queryKey: procurementKeys.ledger(frameworkId ?? ''),
    queryFn: () => getLedger(frameworkId as string),
    enabled: !!frameworkId,
  });
}

/**
 * Refetch everything the module holds after any write. One package change
 * moves thresholds, findings, the schedule and a framework's remaining value
 * at once, so nothing is patched in place.
 */
export function useInvalidateProcurement(projectId: string) {
  const qc = useQueryClient();
  return useCallback(() => {
    void qc.invalidateQueries({ queryKey: procurementKeys.project(projectId) });
    void qc.invalidateQueries({ queryKey: ['procurement-concept-company'] });
  }, [qc, projectId]);
}

/** The sentence for a failed request: the server's refusal by code when it sent one, else the transport error. */
export function refusalText(t: TFn, err: unknown): string {
  const code = procurementErrorCode(err);
  return code ? errorText(t, code, procurementErrorMessage(err)) : getErrorMessage(err);
}

/** An `onError` that shows the server's reason as a toast. */
export function useRefusalToast() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  return useCallback(
    (err: unknown) => {
      addToast({ type: 'error', title: refusalText(t as TFn, err) });
    },
    [addToast, t],
  );
}

export function useLabelContext(): LabelContext {
  const { t, i18n } = useTranslation();
  return useMemo(
    () => ({
      t: t as LabelContext['t'],
      language: i18n.language || 'en',
      exists: (key: string) => (typeof i18n.exists === 'function' ? i18n.exists(key) : false),
    }),
    [t, i18n],
  );
}

export function usePermitLotRequirements(projectId: string, enabled = true) {
  return useQuery({
    queryKey: procurementKeys.permitConditions(projectId),
    queryFn: () => getPermitLotRequirements(projectId),
    enabled: !!projectId && enabled,
  });
}
