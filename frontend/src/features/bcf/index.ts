// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BCF (BIM Collaboration Format) issue capture + register.
 *
 * Public surface for integrators:
 *   - <BcfIssuesPanel projectId bridge? /> - the issue register (list, detail,
 *     comments, inline editing, import/export).
 *   - <BcfIssueModal /> - the standalone "Raise issue here" dialog.
 *   - <CoordinationMode /> - the guided walk through an agenda of issues,
 *     flying a viewer to each one; reports what was settled via onDecision.
 *   - useBcfCapture / captureViewerContext - the capture flow, driven by an
 *     injected BcfViewerBridge so it never couples to a specific viewer.
 *   - bcfApi - the typed REST client.
 */

export { BcfIssuesPanel } from './BcfIssuesPanel';
export type { BcfIssuesPanelProps } from './BcfIssuesPanel';

export { BcfIssueModal } from './BcfIssueModal';
export type { BcfIssueModalProps, BcfMember } from './BcfIssueModal';

export { CoordinationMode } from './CoordinationMode';
export type { CoordinationDecision } from './CoordinationMode';

export {
  useBcfCapture,
  captureViewerContext,
  captureCanvasBase64,
  cameraToBcf,
  hasCapturedContent,
} from './useBcfCapture';
export type {
  BcfViewerBridge,
  ViewerCameraSnapshot,
  ViewerVec3,
  CapturedContext,
  RaiseIssueInput,
  RaiseIssueResult,
} from './useBcfCapture';

export * as bcfApi from './api';
export type {
  Topic,
  TopicCreate,
  TopicUpdate,
  Viewpoint,
  ViewpointCreate,
  ViewpointComponents,
  PerspectiveCamera,
  OrthogonalCamera,
  Vec3,
  BcfComment,
  CommentCreate,
  CommentUpdate,
  BcfImportReport,
  BcfImportIssue,
  BcfVersion,
} from './api';
