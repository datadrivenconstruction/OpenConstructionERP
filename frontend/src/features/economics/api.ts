// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for the economics of a project: the business case, the cost frame
// compared with the estimate and the commitments, and the financing plan.
//
// Backend module: backend/app/modules/economics/router.py, mounted at
// /api/v1/economics/. Every route lives under /projects/{project_id}/. Money
// travels as decimal strings in both directions; the server refuses floats, so
// nothing here converts an amount to a number.

import { API_BASE, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

export type PlanStatus = 'draft' | 'proposed' | 'approved' | 'reopened';
export type FlowKind = 'investment' | 'revenue' | 'operating_cost' | 'residual';
export type FlowSource = 'manual' | 'cost_frame';
export type SourceKind =
  | 'equity'
  | 'shareholder_loan'
  | 'bank_loan'
  | 'bond'
  | 'grant'
  | 'subsidy'
  | 'sale_proceeds'
  | 'other';
export type Severity = 'error' | 'warning';

export interface Finding {
  code: string;
  ref: string;
  severity: Severity;
  [param: string]: unknown;
}

export interface Readiness {
  met: boolean;
  status: PlanStatus;
  proposed: boolean;
  errors: Finding[];
  warnings: Finding[];
}

export interface PlanView {
  exists: boolean;
  id?: string;
  status?: PlanStatus;
  currency?: string;
  classification_standard?: string;
  discount_rate_pct?: string | null;
  horizon_years?: number;
  markup_allowance?: string;
  boq_id?: string | null;
  gates_in_use?: boolean;
  carrier_reason?: string | null;
  editable?: boolean;
  blocks?: Record<string, string | null>;
  readiness?: Readiness;
  approvals?: Approval[];
  /** `edit` is false while the plan is proposed or approved; `records` is the raw right to edit the registers. */
  can: { edit: boolean; manage: boolean; records?: boolean };
}

export interface Approval {
  id: string;
  number: number;
  status: string;
  rationale: string;
  proposed_by: string | null;
  proposed_by_name: string;
  proposed_at: string | null;
  approved_by: string | null;
  approved_by_name: string;
  approved_at: string | null;
  /** `gate` = the governance gate decided, `hand` = a manager approved. */
  approval_source: string | null;
  four_eyes: boolean;
  blocked_reason: string | null;
}

export interface FlowLine {
  id: string;
  kind: FlowKind;
  label: string;
  mode: 'total' | 'per_year';
  source: FlowSource;
  amount: string;
  year_from: number;
  year_to: number;
  escalation_pct: string;
  notes: string;
}

export interface KeyFigures {
  total_investment: string;
  total_revenue: string;
  total_operating_cost: string;
  residual_value: string;
  net_cash_flow: string;
  npv: string | null;
  irr_pct: string | null;
  payback_year: number | null;
  benefit_cost_ratio: string | null;
  yield_on_cost_pct: string | null;
}

export interface BusinessCase {
  currency: string;
  discount_rate_pct: string | null;
  horizon_years: number;
  frame_total: string;
  lines: FlowLine[];
  cash_flow: { year: number; net: string; cumulative: string }[];
  key_figures: KeyFigures;
}

export interface FrameRow {
  id: string;
  code: string;
  title: string;
  basis: string;
  amount: string;
  estimate: string;
  committed: string | null;
  variance: string;
  variance_pct: string | null;
  headroom: string;
}

export interface CostFrame {
  classification_standard: string;
  currency: string;
  bill: { id: string; name: string; currency: string; bill_count: number } | null;
  lines: FrameRow[];
  markups: { name: string; category: string; amount: string }[];
  totals: {
    lines: string;
    markup_allowance: string;
    frame: string;
    estimate_direct: string;
    estimate_assigned: string;
    estimate_unassigned: string;
    unassigned_count: number;
    markups: string;
    estimate: string;
    /** The frame minus the estimate: what rounding and contingency hold back. Negative when the estimate is above. */
    reserve: string;
    variance: string;
    variance_pct: string | null;
    committed: string | null;
    committed_unassigned: string | null;
    committed_available: boolean;
    committed_reason: string;
  };
}

export interface Tranche {
  id: string;
  due_on: string;
  amount: string;
  status: string;
  condition: string;
  drawn_on: string | null;
}

export interface Source {
  id: string;
  kind: SourceKind;
  name: string;
  amount: string;
  share_pct: string | null;
  interest_rate_pct: string | null;
  funding_application_id: string | null;
  award: { code: string; title: string; status: string; amount: string; basis: string } | null;
  notes: string;
  tranche_total: string;
  tranches: Tranche[];
}

export interface Financing {
  currency: string;
  requirement: string;
  coverage: { sources_total: string; shortfall: string; surplus: string; covered: boolean; coverage_pct: string | null };
  sources: Source[];
}

export type SecurityKind = 'performance' | 'warranty' | 'advance_payment' | 'bid' | 'other';
export type SecurityStatus = 'requested' | 'in_place' | 'released' | 'expired';
export type InsuranceKind = 'builders_all_risk' | 'liability' | 'professional_indemnity' | 'other';
export type InsuranceStatus = 'requested' | 'in_place' | 'expired';
export type VatTreatment = 'standard' | 'reverse_charge' | 'exempt' | 'mixed' | 'other';
export type ProcessArea = 'receivables' | 'payables' | 'administration';

export interface Security {
  id: string;
  kind: SecurityKind;
  description: string;
  amount: string;
  issuer: string;
  beneficiary: string;
  reference: string;
  valid_from: string | null;
  valid_until: string | null;
  status: SecurityStatus;
  lapsed: boolean;
  notes: string;
}

export interface Insurance {
  id: string;
  kind: InsuranceKind;
  insurer: string;
  policy_number: string;
  sum_insured: string;
  deductible: string;
  period_from: string | null;
  period_to: string | null;
  status: InsuranceStatus;
  lapsed: boolean;
  notes: string;
}

export interface TaxTreatment {
  vat_treatment: VatTreatment;
  input_tax_deduction: boolean | null;
  notes: string;
  confirmed: boolean;
  confirmed_by: string | null;
  confirmed_by_name: string;
  confirmed_at: string | null;
}

export interface ProcessRow {
  area: ProcessArea;
  description: string;
  owner: string;
  status: 'open' | 'set_up';
  set_up_on: string | null;
  notes: string;
}

export interface Registers {
  securities: Security[];
  insurances: Insurance[];
  tax: TaxTreatment | null;
  process: ProcessRow[];
  state: Record<'securities' | 'insurance' | 'tax' | 'receivables_payables' | 'administration', boolean>;
  findings: Finding[];
}

export const economicsKeys = {
  all: (pid: string) => ['economics', pid] as const,
  plan: (pid: string) => ['economics', pid, 'plan'] as const,
  businessCase: (pid: string) => ['economics', pid, 'business-case'] as const,
  costFrame: (pid: string) => ['economics', pid, 'cost-frame'] as const,
  financing: (pid: string) => ['economics', pid, 'financing'] as const,
  registers: (pid: string) => ['economics', pid, 'registers'] as const,
};

export const getPlan = (pid: string) => apiGet<PlanView>(`/v1/economics/projects/${pid}/plan`);
export const startPlan = (pid: string) => apiPut<PlanView>(`/v1/economics/projects/${pid}/plan`, {});
export const patchPlan = (pid: string, body: Record<string, unknown>) => apiPatch<PlanView>(`/v1/economics/projects/${pid}/plan`, body);
export const getBusinessCase = (pid: string) => apiGet<BusinessCase>(`/v1/economics/projects/${pid}/business-case`);
export const getCostFrame = (pid: string) => apiGet<CostFrame>(`/v1/economics/projects/${pid}/cost-frame`);
export const getFinancing = (pid: string) => apiGet<Financing>(`/v1/economics/projects/${pid}/financing`);

export const getRegisters = (pid: string) => apiGet<Registers>(`/v1/economics/projects/${pid}/registers`);
export const addSecurity = (pid: string, body: Record<string, unknown>) =>
  apiPost<Registers>(`/v1/economics/projects/${pid}/registers/securities`, body);
export const patchSecurity = (pid: string, id: string, body: Record<string, unknown>) =>
  apiPatch<Registers>(`/v1/economics/projects/${pid}/registers/securities/${id}`, body);
export const deleteSecurity = (pid: string, id: string) => apiDelete(`/v1/economics/projects/${pid}/registers/securities/${id}`);
export const addInsurance = (pid: string, body: Record<string, unknown>) =>
  apiPost<Registers>(`/v1/economics/projects/${pid}/registers/insurances`, body);
export const patchInsurance = (pid: string, id: string, body: Record<string, unknown>) =>
  apiPatch<Registers>(`/v1/economics/projects/${pid}/registers/insurances/${id}`, body);
export const deleteInsurance = (pid: string, id: string) => apiDelete(`/v1/economics/projects/${pid}/registers/insurances/${id}`);
export const putTax = (pid: string, body: Record<string, unknown>) => apiPut<Registers>(`/v1/economics/projects/${pid}/registers/tax`, body);
export const putProcess = (pid: string, area: ProcessArea, body: Record<string, unknown>) =>
  apiPut<Registers>(`/v1/economics/projects/${pid}/registers/process/${area}`, body);

export const addFlowLine = (pid: string, body: Record<string, unknown>) =>
  apiPost<unknown>(`/v1/economics/projects/${pid}/business-case/lines`, body);
export const deleteFlowLine = (pid: string, id: string) => apiDelete(`/v1/economics/projects/${pid}/business-case/lines/${id}`);

export const addFrameLine = (pid: string, body: Record<string, unknown>) =>
  apiPost<unknown>(`/v1/economics/projects/${pid}/cost-frame/lines`, body);
export const patchFrameLine = (pid: string, id: string, body: Record<string, unknown>) =>
  apiPatch<unknown>(`/v1/economics/projects/${pid}/cost-frame/lines/${id}`, body);
export const deleteFrameLine = (pid: string, id: string) => apiDelete(`/v1/economics/projects/${pid}/cost-frame/lines/${id}`);
export const generateFrame = (pid: string, body: { depth: number; amounts: 'estimate' | 'zero'; replace: boolean }) =>
  apiPost<unknown>(`/v1/economics/projects/${pid}/cost-frame/generate`, body);

export const addSource = (pid: string, body: Record<string, unknown>) =>
  apiPost<unknown>(`/v1/economics/projects/${pid}/financing/sources`, body);
export const deleteSource = (pid: string, id: string) => apiDelete(`/v1/economics/projects/${pid}/financing/sources/${id}`);
export const addTranche = (pid: string, sourceId: string, body: Record<string, unknown>) =>
  apiPost<unknown>(`/v1/economics/projects/${pid}/financing/sources/${sourceId}/tranches`, body);
export const deleteTranche = (pid: string, id: string) => apiDelete(`/v1/economics/projects/${pid}/financing/tranches/${id}`);

export type Lifecycle = 'propose' | 'withdraw' | 'approve' | 'reopen' | 'reopen/close';
export const runLifecycle = (pid: string, action: Lifecycle, body: Record<string, unknown> = {}) =>
  apiPost<PlanView>(`/v1/economics/projects/${pid}/${action}`, body);

export type ExportWhat = 'frame' | 'case' | 'financing';
export type ExportFormat = 'pdf' | 'xlsx';

/** Download the cost frame, the business case or the financing plan as PDF or XLSX. */
export function downloadExport(projectId: string, what: ExportWhat, format: ExportFormat): Promise<void> {
  return downloadWithAuth(
    `${API_BASE}/v1/economics/projects/${projectId}/export?what=${what}&format=${format}`,
    `economics_${what}.${format}`,
  );
}
