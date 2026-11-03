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
}

export interface OwnerChangeRollup {
  owner_code: string;
  owner_title: string;
  owner_status: string;
  currency: string;
  owner_value: string;
  sub_cost_approved: string;
  sub_cost_pending: string;
  sub_cost_total: string;
  margin: string;
  margin_percent: string | number | null;
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
  amount: string;
  title: string;
  back_to_back: boolean;
}

const BASE = '/v1/subcontractors/changes';

export function getOwnerRollup(type: OwnerChangeType, id: string): Promise<OwnerChangeRollup> {
  return apiGet<OwnerChangeRollup>(`${BASE}/by-owner-change/${type}/${id}`);
}

export function listAgreementChanges(agreementId: string): Promise<SubcontractChange[]> {
  return apiGet<SubcontractChange[]>(`/v1/subcontractors/agreements/${agreementId}/changes/`);
}

export function validateSubChange(id: string): Promise<SubChangeValidation> {
  return apiGet<SubChangeValidation>(`${BASE}/${id}/validate/`);
}

export function splitOwnerChange(
  type: OwnerChangeType,
  id: string,
  lines: SplitLine[],
): Promise<SubcontractChange[]> {
  return apiPost<SubcontractChange[]>(`${BASE}/from-owner-change/`, {
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
  return apiPost<SubcontractChange>(`${BASE}/${id}/${action}/`, body);
}

export function updateSubChange(
  id: string,
  data: Partial<Pick<SubcontractChange, 'title' | 'amount' | 'back_to_back' | 'description'>>,
): Promise<SubcontractChange> {
  return apiPatch<SubcontractChange>(`${BASE}/${id}`, data);
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
