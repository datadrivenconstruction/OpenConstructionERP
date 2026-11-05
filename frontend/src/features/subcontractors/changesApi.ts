/**
 * Subcontract changes: the sub-side of an owner variation order / change order.
 * Backed by /api/v1/subcontractors/changes/.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, apiPatch } from '@/shared/lib/api';

export type OwnerChangeType = 'variation_order' | 'change_order';
export type SubChangeStatus = 'draft' | 'submitted' | 'approved' | 'rejected' | 'withdrawn';

export interface SubcontractChange {
  id: string;
  agreement_id: string;
  project_id: string;
  code: string;
  title: string;
  description?: string | null;
  amount: string;
  currency: string;
  status: SubChangeStatus;
  back_to_back: boolean;
  owner_change_type: OwnerChangeType | null;
  owner_change_id: string | null;
  submitted_at?: string | null;
  decided_at?: string | null;
  decision_note?: string | null;
  applied_amount?: string | null;
  owner_amount?: string | null;
  markup_pct?: string;
  time_impact_days?: number;
  owner_time_days?: number | null;
}

export interface OwnerChangeRollup {
  owner_code: string;
  owner_title: string;
  owner_status: string;
  owner_approved?: boolean;
  currency: string;
  owner_value: string;
  sub_cost_approved: string;
  sub_cost_pending: string;
  sub_cost_total: string;
  margin: string;
  margin_percent: string | number | null;
  approved_sub_total?: string;
  markup_retained?: string;
  /** owner value - approved sub total - GC markup kept; negative = the GC absorbs it. */
  leakage?: string;
  days_owner?: number | null;
  days_sub_total?: number;
  changes: SubcontractChange[];
}

export interface SubChangeValidation {
  status: string;
  results: {
    rule_id: string;
    severity: string;
    passed: boolean;
    message: string;
    suggestion?: string | null;
  }[];
}

export interface SplitLine {
  agreement_id: string;
  /** Omit on a lone back-to-back line: the server derives it from the owner value less markup. */
  amount?: string;
  title: string;
  back_to_back: boolean;
  markup_pct?: number;
  time_impact_days?: number;
}

export interface SovChangeLine {
  change_id: string;
  code: string;
  title: string;
  amount: string;
  currency: string;
  markup_pct: string;
  time_impact_days: number;
}


export function getOwnerRollup(type: OwnerChangeType, id: string): Promise<OwnerChangeRollup> {
  return apiGet<OwnerChangeRollup>(`/v1/subcontractors/changes/by-owner-change/${type}/${id}`);
}

export async function listAgreementChanges(agreementId: string): Promise<SubcontractChange[]> {
  const page = await apiGet<{ items: SubcontractChange[] }>(
    `/v1/subcontractors/agreements/${agreementId}/changes/?limit=500`,
  );
  return page.items;
}

export function validateSubChange(id: string): Promise<SubChangeValidation> {
  return apiGet<SubChangeValidation>(`/v1/subcontractors/changes/${id}/validate/`);
}

export function splitOwnerChange(
  type: OwnerChangeType,
  id: string,
  lines: SplitLine[],
): Promise<SubcontractChange[]> {
  return apiPost<SubcontractChange[]>(`/v1/subcontractors/changes/from-owner-change/`, {
    owner_change_type: type,
    owner_change_id: id,
    lines,
  });
}

export type SubChangeAction = 'submit' | 'approve' | 'reject' | 'withdraw';

export function actOnSubChange(
  id: string,
  action: SubChangeAction,
  note?: string,
): Promise<SubcontractChange> {
  const body = action === 'approve' || action === 'reject' ? { note: note ?? '' } : undefined;
  return apiPost<SubcontractChange>(`/v1/subcontractors/changes/${id}/${action}/`, body);
}

export function updateSubChange(
  id: string,
  data: Partial<Pick<SubcontractChange, 'title' | 'amount' | 'back_to_back' | 'description' | 'markup_pct' | 'time_impact_days'>>,
): Promise<SubcontractChange> {
  return apiPatch<SubcontractChange>(`/v1/subcontractors/changes/${id}`, data);
}

/** Approved changes not yet billed: candidate lines for the next payment application. */
export async function listSovChangeLines(agreementId: string): Promise<SovChangeLine[]> {
  const page = await apiGet<{ items: SovChangeLine[] }>(
    `/v1/subcontractors/agreements/${agreementId}/changes/sov-lines?limit=500`,
  );
  return page.items;
}

export function markChangeBilled(id: string, applicationId: string): Promise<SubcontractChange> {
  return apiPost<SubcontractChange>(`/v1/subcontractors/changes/${id}/mark-billed/`, { application_id: applicationId });
}

export function useOwnerRollup(type: OwnerChangeType, id: string) {
  return useQuery({
    queryKey: ['subcontractors', 'changes', 'owner', type, id],
    queryFn: () => getOwnerRollup(type, id),
    enabled: !!id,
  });
}

export function useAgreementChanges(agreementId: string) {
  return useQuery({
    queryKey: ['subcontractors', 'changes', 'agreement', agreementId],
    queryFn: () => listAgreementChanges(agreementId),
    enabled: !!agreementId,
  });
}

/** Every mutation refreshes all subcontract-change reads (owner strip, agreement lists). */
export function useSubChangeMutations(onError?: (e: unknown) => void) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['subcontractors', 'changes'] });
  const act = useMutation({
    mutationFn: (v: { id: string; action: SubChangeAction; note?: string }) =>
      actOnSubChange(v.id, v.action, v.note),
    onSuccess: invalidate,
    onError,
  });
  const split = useMutation({
    mutationFn: (v: { type: OwnerChangeType; id: string; lines: SplitLine[] }) =>
      splitOwnerChange(v.type, v.id, v.lines),
    onSuccess: invalidate,
    onError,
  });
  return { act, split };
}

export function ownerChangeHref(type: OwnerChangeType | null, id: string | null): string | null {
  if (!type || !id) return null;
  return type === 'variation_order'
    ? `/variations?tab=orders&highlight=${id}`
    : `/changeorders?highlight=${id}`;
}
