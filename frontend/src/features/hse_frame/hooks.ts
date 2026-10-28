// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useCallback, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getCatalogue,
  getChecks,
  getFrame,
  getReadiness,
  getSummary,
  hseKeys,
  listCandidates,
  listItems,
  listRoles,
  refusalOf,
} from './api';

export function useFrame(projectId: string) {
  return useQuery({ queryKey: hseKeys.frame(projectId), queryFn: () => getFrame(projectId), enabled: !!projectId });
}

export function useCatalogue(projectId: string, enabled = true) {
  return useQuery({
    queryKey: hseKeys.catalogue(projectId),
    queryFn: () => getCatalogue(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useItems(projectId: string, enabled = true) {
  return useQuery({
    queryKey: hseKeys.items(projectId),
    queryFn: () => listItems(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useRoles(projectId: string, enabled = true) {
  return useQuery({
    queryKey: hseKeys.roles(projectId),
    queryFn: () => listRoles(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useReadiness(projectId: string, enabled = true) {
  return useQuery({
    queryKey: hseKeys.readiness(projectId),
    queryFn: () => getReadiness(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useSummary(projectId: string, enabled = true) {
  return useQuery({
    queryKey: hseKeys.summary(projectId),
    queryFn: () => getSummary(projectId),
    enabled: !!projectId && enabled,
  });
}

export function useChecks(projectId: string, enabled = true) {
  return useQuery({
    queryKey: hseKeys.checks(projectId),
    queryFn: () => getChecks(projectId).then((p) => p.items),
    enabled: !!projectId && enabled,
  });
}

export function useCandidates(projectId: string, kind: string, q: string) {
  return useQuery({
    queryKey: hseKeys.candidates(projectId, kind, q),
    queryFn: () => listCandidates(projectId, kind, q).then((p) => p.items),
    enabled: !!projectId && !!kind,
  });
}

interface WriteJob {
  run: () => Promise<unknown>;
  done?: (result: unknown) => void;
}

export interface HseWrite {
  send: <T>(run: () => Promise<T>, done?: (result: T) => void) => void;
  pending: boolean;
  /** The server's words for the last refusal; null when the last write went through. */
  refusal: string | null;
}

/**
 * The write hook every panel shares. One write can change readiness, the
 * register and the checks at once, so success refetches the whole project scope.
 */
export function useHseWrite(projectId: string): HseWrite {
  const qc = useQueryClient();
  const [refusal, setRefusal] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (job: WriteJob) => job.run(),
    // The refusal is shown next to the action, in the server's words; the global toast would repeat it.
    meta: { suppressGlobalErrorToast: true },
    onMutate: () => setRefusal(null),
    onSuccess: (result, job) => {
      void qc.invalidateQueries({ queryKey: hseKeys.all(projectId) });
      job.done?.(result);
    },
    onError: (err) => {
      setRefusal(refusalOf(err)?.message ?? (err instanceof Error ? err.message : String(err)));
      void qc.invalidateQueries({ queryKey: hseKeys.all(projectId) });
    },
  });
  const { mutate } = mutation;
  const send = useCallback(
    <T,>(run: () => Promise<T>, done?: (result: T) => void) =>
      mutate({ run, done: done as ((result: unknown) => void) | undefined }),
    [mutate],
  );
  return { send, pending: mutation.isPending, refusal };
}
