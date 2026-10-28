// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wire types for the file-distribution (W10) module. Mirrors
// backend/app/modules/file_distribution/schemas.py.

export type SearchHitKind = 'document' | 'sheet' | 'photo';

export interface SearchHit {
  project_id: string;
  project_name: string;
  file_id: string;
  kind: SearchHitKind;
  canonical_name: string;
  snippet: string;
  score: number;
}

export interface SearchResponse {
  items: SearchHit[];
  total: number;
  used_content_index: boolean;
}

export type DistributionMemberRole = 'for_review' | 'fyi' | 'for_construction';

export interface DistributionMember {
  id: string;
  list_id: string;
  email: string;
  display_name: string | null;
  role: DistributionMemberRole | string | null;
  created_at: string;
}

export interface DistributionList {
  id: string;
  owner_id: string;
  project_id: string | null;
  name: string;
  description: string | null;
  is_shared: boolean;
  members: DistributionMember[];
  created_at: string;
  updated_at: string;
  is_own: boolean;
}

export interface DistributionListListResponse {
  items: DistributionList[];
  total: number;
}

export interface DistributionListCreatePayload {
  name: string;
  description?: string | null;
  project_id?: string | null;
  is_shared?: boolean;
  members?: DistributionMemberCreatePayload[];
}

export interface DistributionListUpdatePayload {
  name?: string;
  description?: string | null;
  is_shared?: boolean;
}

export interface DistributionMemberCreatePayload {
  email: string;
  display_name?: string | null;
  role?: DistributionMemberRole | string | null;
}

export type NotifyEvent = 'created' | 'updated' | 'deleted';

export interface Subscription {
  id: string;
  project_id: string;
  file_kind: string;
  subscriber_email: string;
  subscriber_user_id: string | null;
  notify_on: NotifyEvent[];
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SubscriptionListResponse {
  items: Subscription[];
  total: number;
}

export interface SubscriptionCreatePayload {
  project_id: string;
  file_kind?: string;
  subscriber_email: string;
  subscriber_user_id?: string | null;
  notify_on?: NotifyEvent[];
  active?: boolean;
}
