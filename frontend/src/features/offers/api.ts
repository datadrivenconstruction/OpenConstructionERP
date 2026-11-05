/**
 * API helpers and React Query hooks for customer offers, mounted at `/api/v1/offers`.
 * Money is a decimal STRING on the wire and stays a string here.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type { ScheduleRow } from './schedule';

export type OfferStatus = 'draft' | 'sent' | 'accepted' | 'declined' | 'expired' | 'superseded';
export type OfferSection = 'customer' | 'details' | 'items' | 'schedule' | 'texts' | 'layout';
export type TextKind = 'intro' | 'payment_terms' | 'validity' | 'conditions' | 'warranty' | 'closing' | 'legal_notice';

export const TEXT_KINDS: TextKind[] = ['intro', 'payment_terms', 'validity', 'conditions', 'warranty', 'closing', 'legal_notice'];

export interface OfferSummary {
  id: string;
  project_id: string;
  boq_id: string | null;
  number: string;
  revision: string;
  status: OfferStatus;
  customer_name: string;
  currency: string;
  gross: string;
  valid_until: string | null;
  issue_date: string;
}

export interface OfferPack {
  pack_key: string | null;
  pack_name: string;
  currency: string;
  paper: string;
  validity_days: number;
  title: string;
  alternate_title: string | null;
  tax_modes: string[];
  consumer_rule: boolean;
  [key: string]: unknown;
}

export interface OfferContext {
  project_id: string;
  boq_id: string;
  pack: OfferPack;
  locale: string;
  currency: string;
  client_contact_id: string | null;
  default_validity_days: number;
  default_payment_days: number | null;
  next_number: string;
  document_languages: string[];
  offers: OfferSummary[];
  permissions: Record<string, boolean>;
}

export interface TextEntry {
  source: 'company' | 'project' | 'offer';
  body: string;
  block_id: string | null;
  resolved?: string;
}

export interface OfferTotals {
  net: string;
  tax_total: string;
  gross: string;
  rounding_gap: string;
  tax_groups: { rate: string; base: string; tax: string }[];
  not_included: { ordinal: string; description: string; role: string; total: string }[];
}

export interface Offer {
  id: string;
  project_id: string;
  boq_id: string | null;
  group_id: string;
  number: string;
  revision: string;
  status: OfferStatus;
  contact_id: string | null;
  customer_kind: 'private' | 'business';
  customer: Record<string, unknown> & { name?: string };
  site_same_as_billing: boolean;
  locale: string;
  title: string;
  currency: string;
  tax_mode: string;
  tax_rate: string;
  tax_label: string;
  issue_date: string;
  validity_days: number | null;
  valid_until: string | null;
  payment_days: number | null;
  reference: string;
  markup_presentation: 'spread' | 'lines' | 'section';
  totals: OfferTotals;
  lines: { kind: string; ordinal: string; description: string; role?: string; total?: string }[];
  texts: Record<string, TextEntry>;
  instalments: ScheduleRow[];
  schedule: ScheduleRow[];
  retention_percent: string;
  advance_security: boolean;
  sent_at: string | null;
  contract_id: string | null;
  stale: boolean;
  editable: boolean;
  updated_at: string;
}

export interface OfferFinding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  element_ref: string | null;
  section: OfferSection;
}

export interface OfferValidation {
  findings: OfferFinding[];
  errors: number;
  warnings: number;
  can_send: boolean;
  first_error: string | null;
}

export type OfferPatch = Partial<
  Pick<
    Offer,
    'number' | 'issue_date' | 'valid_until' | 'validity_days' | 'payment_days' | 'reference' | 'locale' | 'title'
    | 'customer_kind' | 'markup_presentation' | 'site_same_as_billing' | 'retention_percent' | 'advance_security'
  > & { contact_id: string | null; texts: Record<string, Pick<TextEntry, 'source' | 'body' | 'block_id'>>; instalments: ScheduleRow[] }
>;

const base = '/v1/offers';

export function useOfferContext(projectId: string | undefined, boqId: string | undefined) {
  return useQuery({
    queryKey: ['offers', 'context', projectId, boqId],
    queryFn: () => apiGet<OfferContext>(`${base}/context?project_id=${projectId}&boq_id=${boqId}`),
    enabled: !!projectId && !!boqId,
  });
}

export function useOffer(id: string | undefined) {
  return useQuery({ queryKey: ['offers', 'offer', id], queryFn: () => apiGet<Offer>(`${base}/${id}`), enabled: !!id });
}

export function useOfferValidation(id: string | undefined, version: string | undefined) {
  return useQuery({
    queryKey: ['offers', 'validation', id, version],
    queryFn: () => apiGet<OfferValidation>(`${base}/${id}/validate`),
    enabled: !!id,
  });
}

export function useCreateOffer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { project_id: string; boq_id: string; contact_id?: string | null }) => apiPost<Offer>(`${base}/`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['offers'] }),
  });
}

export function usePatchOffer(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: OfferPatch) => apiPatch<Offer>(`${base}/${id}`, patch),
    onSuccess: (offer) => {
      qc.setQueryData(['offers', 'offer', id], offer);
      void qc.invalidateQueries({ queryKey: ['offers', 'validation', id] });
    },
  });
}

/** Offer lifecycle actions: send, revise, accept, decline. */
export function useOfferAction(id: string, action: 'send' | 'revise' | 'decline' | 'accept') {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: { accepted_on?: string; optional_ordinals?: string[]; create_contract?: boolean }) =>
      apiPost<Offer | { offer: Offer; contract_id: string | null; milestones: number }>(`${base}/${id}/${action}`, body ?? {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['offers'] }),
  });
}

export function fetchPreview(id: string) {
  return apiGet<{ pdf_base64: string; page_count: number; filename: string }>(`${base}/${id}/preview`);
}

export function numberTaken(number: string, groupId: string) {
  return apiGet<{ number: string; taken: boolean }>(`${base}/number-check?number=${encodeURIComponent(number)}&group_id=${groupId}`);
}
