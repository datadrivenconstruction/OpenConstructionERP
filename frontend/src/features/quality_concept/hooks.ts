// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the quality concept screens, the one write hook every
// panel shares, and the two pieces of context each screen needs: how to name
// a catalogue item and how to name a person.

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { listRoster } from '@/features/teams/api';
import { useAuthStore } from '@/stores/useAuthStore';

import {
  getCatalogue,
  getConcept,
  getCoverage,
  getReadiness,
  getStageMatrix,
  getValidation,
  listCandidates,
  listCatalogues,
  listCertifications,
  getPermitConditionChecks,
  listExpertReports,
  listLinks,
  listOptions,
  listProofs,
  listRequirements,
  listRevisions,
  listStandards,
  listSurveys,
  listUnits,
  qcKeys,
  refusalDetail,
  type Finding,
  type LinkOwnerKind,
  type OptionKind,
} from './api';
import { refusalText, type LabelContext, type TFn } from './labels';

/**
 * The concept. Reading never creates one: a project without a concept answers
 * 404 `concept_missing`, which the page shows as its first-visit state. Every
 * other query waits for this one.
 */
export function useConcept(projectId: string) {
  return useQuery({
    queryKey: qcKeys.concept(projectId),
    queryFn: () => getConcept(projectId),
    enabled: !!projectId,
    retry: false,
  });
}

export function useCatalogue(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.catalogue(projectId),
    queryFn: () => getCatalogue(projectId),
    enabled: !!projectId && enabled,
    staleTime: 5 * 60_000,
  });
}

export function useRevisions(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.revisions(projectId),
    queryFn: () => listRevisions(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useStandards(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.standards(projectId),
    queryFn: () => listStandards(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useRequirements(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.requirements(projectId),
    queryFn: () => listRequirements(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useCertifications(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.certifications(projectId),
    queryFn: () => listCertifications(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useProofs(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.proofs(projectId),
    queryFn: () => listProofs(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useCoverage(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.coverage(projectId),
    queryFn: () => getCoverage(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useEvidenceLinks(projectId: string, ownerKind: LinkOwnerKind, ownerId: string | null) {
  return useQuery({
    queryKey: qcKeys.links(projectId, ownerKind, ownerId ?? ''),
    queryFn: () => listLinks(projectId, ownerKind, ownerId as string).then((p) => p.items),
    enabled: !!projectId && !!ownerId,
  });
}

export function useLinkCandidates(projectId: string, linkKind: string, q: string) {
  return useQuery({
    queryKey: qcKeys.candidates(projectId, linkKind, q),
    queryFn: () => listCandidates(projectId, linkKind, q).then((p) => p.items),
    enabled: !!projectId && !!linkKind,
  });
}

/** The catalogues this project may be pinned to, with whether the reader may pin one. */
export function useCatalogues(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.catalogues(projectId),
    queryFn: () => listCatalogues(projectId),
    enabled: !!projectId && enabled,
  });
}

/** Records of another module to choose from. The whole answer is kept: it may say no list can be offered. */
export function useOptions(projectId: string, kind: OptionKind, q: string) {
  return useQuery({
    queryKey: qcKeys.options(projectId, kind, q),
    queryFn: () => listOptions(projectId, kind, q),
    enabled: !!projectId,
  });
}

export function useStageMatrix(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.matrix(projectId),
    queryFn: () => getStageMatrix(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useAcceptanceUnits(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.units(projectId),
    queryFn: () => listUnits(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useSurveys(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.surveys(projectId),
    queryFn: () => listSurveys(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useExpertReports(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.expertReports(projectId),
    queryFn: () => listExpertReports(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function usePermitConditionChecks(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.permitConditions(projectId),
    queryFn: () => getPermitConditionChecks(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useReadiness(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.readiness(projectId),
    queryFn: () => getReadiness(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useValidation(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qcKeys.validation(projectId),
    queryFn: () => getValidation(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

interface WriteJob {
  run: () => Promise<unknown>;
  done?: (result: unknown) => void;
}

export interface QcWrite {
  /** Run a write. On success everything the module holds for the project is refetched, then `done` runs. */
  send: <T>(run: () => Promise<T>, done?: (result: T) => void) => void;
  pending: boolean;
  /** The server's reason for the last refusal, in the reader's language, or null. */
  refusal: string | null;
  /** Every finding a 422 listed, so the screen can show all of them and not only the first. */
  violations: Finding[];
  clear: () => void;
}

/**
 * The write hook every panel shares. One write can change readiness, coverage
 * and the findings of the concept at once, so success refetches the whole
 * project scope rather than a hand-picked list.
 */
export function useQcWrite(projectId: string): QcWrite {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [refusal, setRefusal] = useState<string | null>(null);
  const [violations, setViolations] = useState<Finding[]>([]);
  const mutation = useMutation({
    mutationFn: (job: WriteJob) => job.run(),
    // The refusal is shown next to the action, in the server's words; the global toast would repeat it.
    meta: { suppressGlobalErrorToast: true },
    onMutate: () => {
      setRefusal(null);
      setViolations([]);
    },
    onSuccess: (result, job) => {
      void qc.invalidateQueries({ queryKey: qcKeys.project(projectId) });
      job.done?.(result);
    },
    onError: (err) => {
      setRefusal(refusalText(t as TFn, err));
      setViolations(refusalDetail(err)?.violations ?? []);
      // A write first follows what other modules decided, so a refusal can mean the concept or a unit moved
      // since it was read. The screen reads again and shows the state the refusal was about.
      void qc.invalidateQueries({ queryKey: qcKeys.project(projectId) });
    },
  });
  const { mutate } = mutation;
  const send = useCallback(
    <T,>(run: () => Promise<T>, done?: (result: T) => void) =>
      mutate({ run, done: done as ((result: unknown) => void) | undefined }),
    [mutate],
  );
  const clear = useCallback(() => {
    setRefusal(null);
    setViolations([]);
  }, []);
  return { send, pending: mutation.isPending, refusal, violations, clear };
}

/** Names for user ids, read from the project roster under the same key the people picker caches it. */
export function usePeopleNames(projectId: string): (userId: string | null | undefined) => string | null {
  const { data: roster = [] } = useQuery({
    queryKey: ['roster', projectId],
    queryFn: () => listRoster(projectId).then((page) => page.items),
    enabled: !!projectId,
    staleTime: 60_000,
  });
  const userId = useAuthStore((s) => s.userId);
  const fullName = useAuthStore((s) => s.userFullName);
  return useMemo(() => {
    const names = new Map<string, string>();
    for (const m of roster) if (m.user_id) names.set(m.user_id, m.display_name || m.email);
    if (userId && fullName && !names.has(userId)) names.set(userId, fullName);
    return (id) => (id ? names.get(id) ?? null : null);
  }, [roster, userId, fullName]);
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
