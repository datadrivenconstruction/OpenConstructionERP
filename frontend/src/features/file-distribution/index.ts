// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Public surface of the file-distribution (W10) feature.

export { GlobalSearchPage, SearchResultCard } from './GlobalSearchPage';
export { DistributionListModal } from './DistributionListModal';
export { SubscribeFolderButton } from './SubscribeFolderButton';
export {
  useGlobalFileSearch,
  useDistributionLists,
  useCreateDistributionList,
  useUpdateDistributionList,
  useDeleteDistributionList,
  useAddDistributionMember,
  useRemoveDistributionMember,
  useSubscriptions,
  useCreateSubscription,
  useDeleteSubscription,
  fileDistributionKeys,
} from './hooks';
export type {
  SearchHit,
  SearchHitKind,
  SearchResponse,
  DistributionList,
  DistributionMember,
  DistributionMemberRole,
  DistributionListCreatePayload,
  DistributionListUpdatePayload,
  DistributionMemberCreatePayload,
  Subscription,
  SubscriptionCreatePayload,
  NotifyEvent,
} from './types';
