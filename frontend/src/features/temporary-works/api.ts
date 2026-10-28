// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Temporary Works governance.
 *
 * Safety-critical falsework / propping / excavation-support lifecycle:
 * design-check -> permit-to-load -> inspection -> permit-to-strike.
 *
 * Every endpoint is scoped to a project in its path:
 *   /v1/temporary-works/projects/{projectId}/...
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* -- Vocabularies (in lock-step with the backend register core) ------------ */

export type TWType =
  | 'falsework'
  | 'formwork'
  | 'propping'
  | 'excavation_support'
  | 'scaffold'
  | 'facade_retention'
  | 'crane_base'
  | 'edge_protection'
  | 'dewatering'
  | 'hoarding'
  | 'other';

export type ItemStatus =
  | 'identified'
  | 'design_brief'
  | 'design_submitted'
  | 'design_checked'
  | 'approved_to_load'
  | 'loaded'
  | 'in_use'
  | 'approved_to_strike'
  | 'struck'
  | 'removed'
  | 'on_hold';

export type DesignCheckCategory = '0' | '1' | '2' | '3';

export type PermitType = 'permit_to_load' | 'permit_to_strike' | 'permit_to_dismantle';

export type PermitStatus = 'draft' | 'issued' | 'active' | 'expired' | 'closed';

/* -- Types ----------------------------------------------------------------- */

export interface TemporaryWorksItem {
  id: string;
  project_id: string;
  reference: string;
  title: string;
  description: string | null;
  tw_type: TWType;
  design_check_category: DesignCheckCategory | null;
  designer_name: string | null;
  checker_name: string | null;
  twc_name: string | null;
  twc_user_id: string | null;
  status: ItemStatus;
  required_load_date: string | null;
  required_strike_date: string | null;
  design_due_date: string | null;
  location: string | null;
  sort_order: number;
  notes: string | null;
  formwork_assignment_id: string | null;
  design_document_id: string | null;
  check_certificate_document_id: string | null;
  schedule_activity_id: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface TemporaryWorksPermit {
  id: string;
  project_id: string;
  item_id: string;
  permit_number: string;
  permit_type: PermitType;
  status: PermitStatus;
  issued_by: string | null;
  issued_at: string | null;
  valid_from: string | null;
  valid_to: string | null;
  closed_at: string | null;
  closed_by: string | null;
  inspection_id: string | null;
  prereq_design_check_accepted: boolean;
  prereq_inspection_passed: boolean;
  conditions: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

/** Per-item load / strike clearance, from the load-status view. */
export interface ItemGateStatus {
  item_id: string | null;
  reference: string;
  cleared_to_load: boolean;
  cleared_to_strike: boolean;
}

/** One compliance breach: an item bearing load with no valid permit to load. */
export interface ComplianceBreach {
  item_id: string | null;
  reference: string;
  title: string;
  reason: string;
}

/** A lightweight item reference used in overdue lists. */
export interface ItemRef {
  item_id: string | null;
  reference: string;
  title: string;
  tw_type: string;
  status: string;
  required_load_date: string | null;
  required_strike_date: string | null;
}

/** The safety-first load-status summary: gates plus the breach list. */
export interface LoadStatus {
  project_id: string;
  as_of: string;
  total: number;
  is_compliant: boolean;
  gate_statuses: ItemGateStatus[];
  compliance_breaches: ComplianceBreach[];
}

/** The full register rollup: counts, clearance, overdue, breaches, gates. */
export interface RegisterRollup {
  project_id: string;
  as_of: string;
  total: number;
  status_counts: Record<string, number>;
  category_counts: Record<string, number>;
  /** Plain decimal string (never a float), or null when the register is empty. */
  design_clearance_pct: string | null;
  is_compliant: boolean;
  overdue_to_load: ItemRef[];
  overdue_to_strike: ItemRef[];
  compliance_breaches: ComplianceBreach[];
  gate_statuses: ItemGateStatus[];
}

/* -- Payloads -------------------------------------------------------------- */

export interface ItemFilters {
  tw_type?: TWType | '';
  status?: ItemStatus | '';
  category?: DesignCheckCategory | '';
}

export interface CreateItemPayload {
  reference: string;
  title: string;
  tw_type: TWType;
  status?: ItemStatus;
  design_check_category?: DesignCheckCategory | null;
  designer_name?: string | null;
  checker_name?: string | null;
  twc_name?: string | null;
  location?: string | null;
  required_load_date?: string | null;
  required_strike_date?: string | null;
  design_due_date?: string | null;
  description?: string | null;
  notes?: string | null;
}

export type UpdateItemPayload = Partial<CreateItemPayload>;

export interface CreatePermitPayload {
  permit_number: string;
  permit_type: PermitType;
  status?: PermitStatus;
  issued_by?: string | null;
  issued_at?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  closed_at?: string | null;
  conditions?: string | null;
  prereq_design_check_accepted?: boolean;
  prereq_inspection_passed?: boolean;
}

export type UpdatePermitPayload = Partial<CreatePermitPayload>;

/* -- API functions --------------------------------------------------------- */

const base = (projectId: string): string => `/v1/temporary-works/projects/${projectId}`;

export async function fetchItems(
  projectId: string,
  filters?: ItemFilters,
): Promise<TemporaryWorksItem[]> {
  if (!projectId) return [];
  const params = new URLSearchParams();
  if (filters?.tw_type) params.set('tw_type', filters.tw_type);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.category) params.set('category', filters.category);
  const qs = params.toString();
  return apiGet<TemporaryWorksItem[]>(`${base(projectId)}/items${qs ? `?${qs}` : ''}`);
}

export async function createItem(
  projectId: string,
  data: CreateItemPayload,
): Promise<TemporaryWorksItem> {
  return apiPost<TemporaryWorksItem>(`${base(projectId)}/items`, data);
}

export async function updateItem(
  projectId: string,
  itemId: string,
  data: UpdateItemPayload,
): Promise<TemporaryWorksItem> {
  return apiPatch<TemporaryWorksItem>(`${base(projectId)}/items/${itemId}`, data);
}

export async function deleteItem(projectId: string, itemId: string): Promise<void> {
  return apiDelete(`${base(projectId)}/items/${itemId}`);
}

export async function fetchPermits(
  projectId: string,
  itemId?: string,
): Promise<TemporaryWorksPermit[]> {
  if (!projectId) return [];
  const params = new URLSearchParams();
  if (itemId) params.set('item_id', itemId);
  const qs = params.toString();
  return apiGet<TemporaryWorksPermit[]>(`${base(projectId)}/permits${qs ? `?${qs}` : ''}`);
}

export async function createPermit(
  projectId: string,
  itemId: string,
  data: CreatePermitPayload,
): Promise<TemporaryWorksPermit> {
  return apiPost<TemporaryWorksPermit>(`${base(projectId)}/items/${itemId}/permits`, data);
}

export async function updatePermit(
  projectId: string,
  permitId: string,
  data: UpdatePermitPayload,
): Promise<TemporaryWorksPermit> {
  return apiPatch<TemporaryWorksPermit>(`${base(projectId)}/permits/${permitId}`, data);
}

export async function fetchLoadStatus(projectId: string): Promise<LoadStatus> {
  return apiGet<LoadStatus>(`${base(projectId)}/load-status`);
}

export async function fetchRegister(projectId: string): Promise<RegisterRollup> {
  return apiGet<RegisterRollup>(`${base(projectId)}/register`);
}
