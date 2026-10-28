// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - server state for authored cases.
//
// The 144 shipped cases are a build-time glob, so they are simply there. An
// authored case is a row on the server, so it needs fetching, and the two have
// to end up in one list that the hub filters and the runner walks. That
// conversion is `caseToPlaybook` in ./api; this file is only the fetching and
// the cache invalidation around it.
//
// A failure here is deliberately quiet. If the cases endpoint is unreachable,
// the hub still shows all 144 shipped cases rather than an error page: losing
// the authored ones is a degraded list, not a broken screen.

import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Playbook } from './types';
import type { CaseBody, CaseResponse, CaseSaveResponse } from './api';
import {
  AUTHORED_CASE_ORDER_BASE,
  caseToPlaybook,
  createCase,
  deleteCase,
  duplicateCase,
  fetchCase,
  fetchCases,
  updateCase,
} from './api';

export const CASES_QUERY_KEY = ['cases', 'authored'] as const;

/** Every authored case the signed-in user may read: their own plus shared. */
export function useAuthoredCases() {
  const query = useQuery({
    queryKey: CASES_QUERY_KEY,
    queryFn: () => fetchCases(),
    // The list changes only when somebody edits a case, and every edit path in
    // this app invalidates the key explicitly, so polling would be waste.
    staleTime: 60_000,
    retry: 1,
  });

  const playbooks = useMemo<Playbook[]>(() => {
    const rows = query.data ?? [];
    // `order` is not stored. Index off a base above every shipped case so the
    // authored ones keep the order the server returned and sort after the
    // product's own examples rather than interleaving with them.
    return rows.map((row, index) => caseToPlaybook(row, AUTHORED_CASE_ORDER_BASE + index));
  }, [query.data]);

  return {
    cases: query.data ?? ([] as CaseResponse[]),
    playbooks,
    isLoading: query.isLoading,
    // Not surfaced as an error page on purpose - see the file header.
    failed: query.isError,
  };
}

/** One authored case, for the editor. Skipped when there is no id (a new case). */
export function useAuthoredCase(caseId: string | null) {
  return useQuery({
    queryKey: [...CASES_QUERY_KEY, caseId],
    queryFn: () => fetchCase(caseId as string),
    enabled: Boolean(caseId),
    retry: 1,
  });
}

/** Create, update, delete and fork, each invalidating the shared list. */
export function useCaseMutations() {
  const queryClient = useQueryClient();
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: CASES_QUERY_KEY });
  };

  const create = useMutation<CaseSaveResponse, Error, CaseBody>({
    mutationFn: (body) => createCase(body),
    onSuccess: invalidate,
  });

  const update = useMutation<CaseSaveResponse, Error, { caseId: string; body: CaseBody }>({
    mutationFn: ({ caseId, body }) => updateCase(caseId, body),
    onSuccess: invalidate,
  });

  const remove = useMutation<void, Error, string>({
    mutationFn: (caseId) => deleteCase(caseId),
    onSuccess: invalidate,
  });

  const fork = useMutation<CaseResponse, Error, { caseId: string; title?: string }>({
    mutationFn: ({ caseId, title }) => duplicateCase(caseId, title),
    onSuccess: invalidate,
  });

  return { create, update, remove, fork };
}
