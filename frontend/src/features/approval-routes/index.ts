// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Public surface of the Approval Routes feature.

export { ApprovalRoutesPage } from './ApprovalRoutesPage';
export { ApprovalInstanceCard } from './ApprovalInstanceCard';
export type { ApprovalInstanceCardProps } from './ApprovalInstanceCard';
export { ApprovalTargetBadge } from './ApprovalTargetBadge';
export type { ApprovalTargetBadgeProps } from './ApprovalTargetBadge';
export { ApprovalInstancesList } from './ApprovalInstancesList';
export { ApprovalAnalyticsPanel } from './ApprovalAnalyticsPanel';
export type { ApprovalAnalyticsPanelProps } from './ApprovalAnalyticsPanel';
export { ApprovalInstanceDetailDrawer } from './ApprovalInstanceDetailDrawer';
export type { ApprovalInstanceDetailDrawerProps } from './ApprovalInstanceDetailDrawer';
export { ReassignDialog } from './ReassignDialog';
export type { ReassignDialogProps } from './ReassignDialog';
export { DelegationManager } from './DelegationManager';
export type { DelegationManagerProps } from './DelegationManager';
export { RouteEditor } from './RouteEditor';
export * as approvalRoutesApi from './api';
export type {
  ApprovalRoute,
  ApprovalRouteCreatePayload,
  ApprovalRouteUpdatePayload,
  ApprovalRoutesMeta,
  ApprovalInstance,
  ApprovalDelegation,
  DelegationCreatePayload,
  DelegationRole,
  InstanceCreatePayload,
  InstanceDecidePayload,
  InstanceCancelPayload,
  InstanceReassignPayload,
  InstanceStatus,
  RouteStep,
  RouteStepMode,
  RouteStepPayload,
  StepState,
  StepDecision,
  StepDecisionState,
  ApprovalAnalytics,
  ApprovalAnalyticsKpis,
  ApprovalAnalyticsRoleStat,
  ApprovalAnalyticsStepStat,
  ApprovalAnalyticsBottleneck,
} from './types';
