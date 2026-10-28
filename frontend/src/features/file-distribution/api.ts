// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for the file-distribution (W10) module.

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type {
  DistributionList,
  DistributionListCreatePayload,
  DistributionListListResponse,
  DistributionListUpdatePayload,
  DistributionMember,
  DistributionMemberCreatePayload,
  SearchHitKind,
  SearchResponse,
  Subscription,
  SubscriptionCreatePayload,
  SubscriptionListResponse,
} from './types';

const BASE = '/v1/file-distribution';

export async function globalFileSearch(params: {
  q: string;
  kinds?: SearchHitKind[];
  limit?: number;
}): Promise<SearchResponse> {
  const search = new URLSearchParams();
  search.set('q', params.q);
  if (params.kinds && params.kinds.length > 0) {
    search.set('kinds', params.kinds.join(','));
  }
  if (params.limit !== undefined) search.set('limit', String(params.limit));
  return apiGet<SearchResponse>(`${BASE}/search/?${search.toString()}`);
}

// ── Distribution lists ──────────────────────────────────────────────────

export async function fetchDistributionLists(
  projectId: string | null | undefined,
): Promise<DistributionListListResponse> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiGet<DistributionListListResponse>(`${BASE}/lists/${qs}`);
}

export async function createDistributionList(
  payload: DistributionListCreatePayload,
): Promise<DistributionList> {
  return apiPost<DistributionList, DistributionListCreatePayload>(
    `${BASE}/lists/`,
    payload,
  );
}

export async function updateDistributionList(
  id: string,
  payload: DistributionListUpdatePayload,
): Promise<DistributionList> {
  return apiPatch<DistributionList, DistributionListUpdatePayload>(
    `${BASE}/lists/${id}/`,
    payload,
  );
}

export async function deleteDistributionList(id: string): Promise<void> {
  await apiDelete<void>(`${BASE}/lists/${id}/`);
}

export async function addDistributionMember(
  listId: string,
  payload: DistributionMemberCreatePayload,
): Promise<DistributionMember> {
  return apiPost<DistributionMember, DistributionMemberCreatePayload>(
    `${BASE}/lists/${listId}/members/`,
    payload,
  );
}

export async function removeDistributionMember(
  listId: string,
  memberId: string,
): Promise<void> {
  await apiDelete<void>(`${BASE}/lists/${listId}/members/${memberId}/`);
}

// ── Subscriptions ──────────────────────────────────────────────────────

export async function fetchSubscriptions(
  projectId: string | null | undefined,
): Promise<SubscriptionListResponse> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiGet<SubscriptionListResponse>(`${BASE}/subscriptions/${qs}`);
}

export async function createSubscription(
  payload: SubscriptionCreatePayload,
): Promise<Subscription> {
  return apiPost<Subscription, SubscriptionCreatePayload>(
    `${BASE}/subscriptions/`,
    payload,
  );
}

export async function deleteSubscription(id: string): Promise<void> {
  await apiDelete<void>(`${BASE}/subscriptions/${id}/`);
}
