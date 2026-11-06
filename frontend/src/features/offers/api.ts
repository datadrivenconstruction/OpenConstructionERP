/**
 * API helpers and React Query hooks for customer offers, mounted at `/api/v1/offers`.
 * Money is a decimal STRING on the wire and stays a string here.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
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
  country?: string;
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

export function useOfferContext(projectId: string | undefined, boqId: string | undefined) {
  return useQuery({
    queryKey: ['offers', 'context', projectId, boqId],
    queryFn: () => apiGet<OfferContext>(`/v1/offers/context?project_id=${projectId}&boq_id=${boqId}`),
    enabled: !!projectId && !!boqId,
  });
}

export function useOffer(id: string | undefined) {
  return useQuery({ queryKey: ['offers', 'offer', id], queryFn: () => apiGet<Offer>(`/v1/offers/${id}`), enabled: !!id });
}

export function useOfferValidation(id: string | undefined, version: string | undefined) {
  return useQuery({
    queryKey: ['offers', 'validation', id, version],
    queryFn: () => apiGet<OfferValidation>(`/v1/offers/${id}/validate`),
    enabled: !!id,
  });
}

export function useCreateOffer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { project_id: string; boq_id: string; contact_id?: string | null }) => apiPost<Offer>(`/v1/offers/`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['offers'] }),
  });
}

export function usePatchOffer(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: OfferPatch) => apiPatch<Offer>(`/v1/offers/${id}`, patch),
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
      apiPost<Offer | { offer: Offer; contract_id: string | null; milestones: number }>(`/v1/offers/${id}/${action}`, body ?? {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['offers'] }),
  });
}

export function fetchPreview(id: string) {
  return apiGet<{ pdf_base64: string; page_count: number; filename: string }>(`/v1/offers/${id}/preview`);
}

export function numberTaken(number: string, groupId: string) {
  return apiGet<{ number: string; taken: boolean }>(`/v1/offers/number-check?number=${encodeURIComponent(number)}&group_id=${groupId}`);
}

export interface AcceptBody {
  accepted_on?: string;
  optional_ordinals?: string[];
  create_contract?: boolean;
}

export interface AcceptResult {
  offer: Offer;
  contract_id: string | null;
  milestones: number;
  /** Set to the missing permission when the contract could not be created. */
  contract_blocked: string | null;
}

export function useAcceptOffer(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AcceptBody) => apiPost<AcceptResult>(`/v1/offers/${id}/accept`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['offers'] }),
  });
}

export function useResetOfferText(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (kind: string) => apiPost<Offer>(`/v1/offers/${id}/texts/${kind}/reset`, {}),
    onSuccess: (offer) => qc.setQueryData(['offers', 'offer', id], offer),
  });
}

/** The placeholders a text may use, as the server whitelists them. */
export const TEXT_PLACEHOLDERS = [
  'offer_number', 'revision', 'issue_date', 'valid_until', 'validity_days', 'payment_days', 'customer_name',
  'project_name', 'site_address', 'net_total', 'gross_total', 'currency', 'retention_percent', 'advance_percent',
] as const;

/** Insert `token` into `text` at the caret, replacing any selection. */
export function insertAt(text: string, start: number, end: number, token: string): { text: string; caret: number } {
  return { text: `${text.slice(0, start)}${token}${text.slice(end)}`, caret: start + token.length };
}

export interface CreatedContact {
  id: string;
  company_name?: string | null;
  first_name?: string | null;
  last_name?: string | null;
}

/** Create the customer in place and optionally make it the project's client. */
export async function createCustomer(input: {
  name: string;
  email: string;
  country: string;
  projectId: string;
  setAsProjectClient: boolean;
}): Promise<CreatedContact> {
  const isPerson = !/\b(gmbh|ltd|llc|inc|ag|sarl|sas|bv|co)\b/i.test(input.name);
  const [first = '', ...rest] = input.name.trim().split(/\s+/);
  const contact = await apiPost<CreatedContact>('/v1/contacts/', {
    contact_type: 'client',
    party_kind: isPerson ? 'person' : 'company',
    ...(isPerson ? { first_name: first, last_name: rest.join(' ') || undefined } : { company_name: input.name.trim() }),
    primary_email: input.email || undefined,
    country_code: input.country || undefined,
  });
  if (input.setAsProjectClient) await apiPatch(`/v1/projects/${input.projectId}`, { client_id: contact.id });
  return contact;
}

export interface OfferSettings {
  number_pattern: string;
  validity_days: number | null;
  payment_days: number | null;
  markup_presentation: 'spread' | 'lines' | 'section';
  schedule_templates: { name: string; rows: ScheduleRow[] }[];
  default_schedule: string;
  next_number: string;
}

/** The page envelope every offers list answers with. */
export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface TextBlock {
  id: string;
  scope: 'company' | 'project';
  project_id: string | null;
  kind: TextKind;
  name: string;
  language: string;
  body: string;
  is_default: boolean;
  pack_key: string | null;
}

export function useOfferSettings() {
  return useQuery({ queryKey: ['offers', 'settings'], queryFn: () => apiGet<OfferSettings>(`/v1/offers/settings`) });
}

export function useSaveOfferSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<Omit<OfferSettings, 'next_number'>>) => apiPatch<OfferSettings>(`/v1/offers/settings`, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['offers'] }),
  });
}

/** The company texts plus this project's overrides; the server caps the library at 1000. */
export async function fetchTextBlocks(projectId?: string, country?: string): Promise<TextBlock[]> {
  const qs = new URLSearchParams();
  if (projectId) qs.set('project_id', projectId);
  if (country) qs.set('country', country);
  qs.set('limit', '1000');
  return (await apiGet<Page<TextBlock>>(`/v1/offers/texts?${qs.toString()}`)).items;
}

export function useTextBlocks(projectId?: string, country?: string) {
  return useQuery({ queryKey: ['offers', 'texts', projectId, country], queryFn: () => fetchTextBlocks(projectId, country) });
}

export function useSaveTextBlock() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<TextBlock> & { id?: string; kind: TextKind }) =>
      id ? apiPatch<TextBlock>(`/v1/offers/texts/${id}`, body) : apiPost<TextBlock>(`/v1/offers/texts`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['offers', 'texts'] }),
  });
}

export function useDeleteTextBlock() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/offers/texts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['offers', 'texts'] }),
  });
}

export function useRestoreTexts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (country: string) => apiPost<{ restored: number }>(`/v1/offers/texts/restore?country=${country}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['offers', 'texts'] }),
  });
}

export async function fetchProjectOffers(projectId: string): Promise<OfferSummary[]> {
  return (await apiGet<Page<OfferSummary>>(`/v1/offers/?project_id=${projectId}&limit=500`)).items;
}

export function useProjectOffers(projectId: string | undefined) {
  return useQuery({
    queryKey: ['offers', 'project', projectId],
    queryFn: () => fetchProjectOffers(projectId as string),
    enabled: !!projectId,
  });
}
