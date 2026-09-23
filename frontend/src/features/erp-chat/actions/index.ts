// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The assistant's proposed changes: cards, the review tray, the Changes ledger
 * and the state they share. See useChatActions.ts for how one action shown in
 * two places stays in sync.
 */
export { ActionProposalCard, ActionProposalRenderer } from './ActionProposalCard';
export type { ActionProposalCardProps } from './ActionProposalCard';
export { ActionsReviewTray, revealFirstWaitingAction } from './ActionsReviewTray';
export type { ActionsReviewTrayProps } from './ActionsReviewTray';
export { ChangesView } from './ChangesView';
export type { ChangesViewProps } from './ChangesView';
export { ActionStatusPill } from './ActionStatusPill';
export type { ActionStatusPillProps } from './ActionStatusPill';
export { ActionFieldTable } from './ActionFieldTable';
export type { ActionFieldTableProps } from './ActionFieldTable';
export { actionIcon } from './actionIcons';
export {
  chatActionKeys,
  pendingActions,
  useChatAction,
  useChatActionStore,
  useChatActionsList,
  useLiveChatActions,
} from './useChatActions';
export { isChatAction, normalizeChatAction } from './types';
export type {
  ActionField,
  ActionFieldKind,
  ActionNote,
  ActionStatus,
  ChatAction,
  ChatActionCounts,
  ChatActionListFilters,
  ChatActionListResponse,
} from './types';
