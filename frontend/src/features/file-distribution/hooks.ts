// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the file-distribution (W10) module.

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  addDistributionMember,
  createDistributionList,
  createSubscription,
  deleteDistributionList,
  deleteSubscription,
  fetchDistributionLists,
  fetchSubscriptions,
  globalFileSearch,
  removeDistributionMember,
  updateDistributionList,
} from './api';
import type {
  DistributionListCreatePayload,
  DistributionListListResponse,
  DistributionListUpdatePayload,
  DistributionMemberCreatePayload,
  SearchHitKind,
  SearchResponse,
  SubscriptionCreatePayload,
  SubscriptionListResponse,
} from './types';

const SEARCH_KEY = 'file-distribution-search';
const LISTS_KEY = 'file-distribution-lists';
const SUBS_KEY = 'file-distribution-subscriptions';

export const fileDistributionKeys = {
  search: SEARCH_KEY,
  lists: LISTS_KEY,
  subscriptions: SUBS_KEY,
};

export function useGlobalFileSearch(params: {
  q: string;
  kinds?: SearchHitKind[];
  limit?: number;
  enabled?: boolean;
}) {
  const enabled = (params.enabled ?? true) && params.q.trim().length > 0;
  return useQuery<SearchResponse>({
    queryKey: [SEARCH_KEY, params.q, params.kinds ?? null, params.limit ?? 50],
    queryFn: () =>
      globalFileSearch({
        q: params.q,
        kinds: params.kinds,
        limit: params.limit,
      }),
    enabled,
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  });
}

export function useDistributionLists(projectId: string | null | undefined) {
  return useQuery<DistributionListListResponse>({
    queryKey: [LISTS_KEY, projectId ?? null],
    queryFn: () => fetchDistributionLists(projectId),
    staleTime: 30_000,
  });
}

export function useCreateDistributionList(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: DistributionListCreatePayload) =>
      createDistributionList(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LISTS_KEY, projectId ?? null] });
    },
  });
}

export function useUpdateDistributionList(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: DistributionListUpdatePayload;
    }) => updateDistributionList(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LISTS_KEY, projectId ?? null] });
    },
  });
}

export function useDeleteDistributionList(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteDistributionList(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LISTS_KEY, projectId ?? null] });
    },
  });
}

export function useAddDistributionMember(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      listId,
      payload,
    }: {
      listId: string;
      payload: DistributionMemberCreatePayload;
    }) => addDistributionMember(listId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LISTS_KEY, projectId ?? null] });
    },
  });
}

export function useRemoveDistributionMember(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ listId, memberId }: { listId: string; memberId: string }) =>
      removeDistributionMember(listId, memberId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [LISTS_KEY, projectId ?? null] });
    },
  });
}

export function useSubscriptions(projectId: string | null | undefined) {
  return useQuery<SubscriptionListResponse>({
    queryKey: [SUBS_KEY, projectId ?? null],
    queryFn: () => fetchSubscriptions(projectId),
    staleTime: 30_000,
  });
}

export function useCreateSubscription(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: SubscriptionCreatePayload) => createSubscription(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [SUBS_KEY, projectId ?? null] });
    },
  });
}

export function useDeleteSubscription(projectId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteSubscription(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [SUBS_KEY, projectId ?? null] });
    },
  });
}
