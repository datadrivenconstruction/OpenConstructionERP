// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wire types for File Approvals (W8).
// Mirrors backend/app/modules/file_approvals/schemas.py — keep in sync.

export type WorkflowStatus = 'in_review' | 'approved' | 'rejected' | 'withdrawn';
export type StepDecision = 'pending' | 'approved' | 'rejected' | 'delegated';

export type FileKind =
  | 'document'
  | 'photo'
  | 'sheet'
  | 'bim_model'
  | 'dwg_drawing'
  | 'takeoff'
  | 'report'
  | 'markup';

export interface StampTemplate {
  id: string;
  project_id: string | null;
  name: string;
  text: string;
  color: string;
  svg_template: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ApprovalStep {
  id: string;
  workflow_id: string;
  sort_order: number;
  approver_id: string;
  role_label: string | null;
  decision: StepDecision | string;
  decision_at: string | null;
  decision_note: string | null;
}

export interface ApprovalWorkflow {
  id: string;
  project_id: string;
  file_kind: FileKind;
  file_id: string;
  file_version_snapshot: string | null;
  submitted_by_id: string | null;
  submitted_at: string;
  status: WorkflowStatus | string;
  final_decision_at: string | null;
  final_decision_by_id: string | null;
  stamp_template_id: string | null;
  stamped_artifact_path: string | null;
  notes: string | null;
  steps: ApprovalStep[];
  created_at: string;
  updated_at: string;
}

export interface ApprovalStepPayload {
  approver_id: string;
  role_label?: string | null;
}

export interface ApprovalWorkflowCreatePayload {
  project_id: string;
  file_kind: FileKind;
  file_id: string;
  file_version_snapshot?: string | null;
  stamp_template_id?: string | null;
  notes?: string | null;
  steps: ApprovalStepPayload[];
}

export interface ApprovalDecidePayload {
  decision: 'approved' | 'rejected' | 'delegated';
  decision_note?: string | null;
}

export interface StampTemplatePayload {
  project_id?: string | null;
  name: string;
  text: string;
  color: string;
  svg_template: string;
  is_active?: boolean;
}
