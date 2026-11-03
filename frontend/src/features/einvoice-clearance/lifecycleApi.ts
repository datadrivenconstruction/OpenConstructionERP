// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Lifecycle, setup and consolidated-document calls. Deadlines, actions and
 * findings are computed server-side from the country's mandate file; this file
 * only types and fetches them.
 */
import { apiGet, apiPost } from '@/shared/lib/api';
import type { DocumentSaveResult } from './api';

export type DeadlineState = 'ok' | 'warning' | 'overdue';

export interface LifecycleDeadline {
  id: string;
  action: 'submit' | 'cancel' | string;
  starts_at: string;
  due_at: string;
  state: DeadlineState;
  seconds_left: number;
}

export interface LifecycleFinding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info' | string;
  message: string;
  params: Record<string, unknown>;
}

export type LifecycleAction = 'validate' | 'send' | 'download' | 'cancel' | 'correct' | 'check_status';

export interface DocumentLifecycle {
  document_id: string;
  country: string;
  platform: string;
  status: string;
  mode: '' | 'export' | 'sandbox' | 'live' | string;
  document_kind: string;
  identifier_label: string;
  authority_identifier: string;
  deadlines: LifecycleDeadline[];
  allowed_actions: LifecycleAction[];
  findings: LifecycleFinding[];
  has_consolidation: boolean;
}

export interface EInvoiceSetupRow {
  country: string;
  platform: string;
  label: string;
  profile_id: string | null;
  mode: string;
  ready: boolean;
  missing: string[];
  has_consolidation: boolean;
}

export interface OverviewRow {
  id: string;
  invoice_id: string | null;
  invoice_number: string;
  invoice_date: string;
  buyer_name: string;
  currency_code: string;
  total_amount: string;
  country: string;
  status: string;
  document_kind: string;
  deadline: LifecycleDeadline | null;
  blocking: number;
}

export interface ConsolidatedReceipt {
  number: string;
  date: string;
  net: string;
  tax: string;
  gross: string;
  source_id: string;
  reason?: string | null;
}

export interface ConsolidatedPreview {
  period: string;
  due_date: string | null;
  count: number;
  net: string;
  tax: string;
  total: string;
  currency_code: string;
  included: ConsolidatedReceipt[];
  excluded: ConsolidatedReceipt[];
}

export interface ConsolidatedBody {
  project_id: string;
  profile_id: string;
  period: string;
}

export function getEInvoiceSetup(): Promise<EInvoiceSetupRow[]> {
  return apiGet<EInvoiceSetupRow[]>(`/v1/einvoice-clearance/setup/`);
}

export function getDocumentLifecycle(documentId: string): Promise<DocumentLifecycle> {
  return apiGet<DocumentLifecycle>(`/v1/einvoice-clearance/documents/${encodeURIComponent(documentId)}/lifecycle`);
}

export function getDocumentsOverview(projectId: string): Promise<OverviewRow[]> {
  return apiGet<OverviewRow[]>(`/v1/einvoice-clearance/documents/overview?project_id=${encodeURIComponent(projectId)}`);
}

export function previewConsolidated(body: ConsolidatedBody): Promise<ConsolidatedPreview> {
  return apiPost<ConsolidatedPreview, ConsolidatedBody>(`/v1/einvoice-clearance/consolidated/preview`, body);
}

export function createConsolidated(body: ConsolidatedBody): Promise<DocumentSaveResult> {
  return apiPost<DocumentSaveResult, ConsolidatedBody>(`/v1/einvoice-clearance/consolidated/`, body);
}
