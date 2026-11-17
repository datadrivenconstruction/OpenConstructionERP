// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for sealed estimates, backed by /api/v1/estimate-archive/
 * (backend/app/modules/estimate_archive/router.py).
 */

import { apiGet, apiPost, downloadWithAuth } from '@/shared/lib/api';

const BASE = '/v1/estimate-archive';

export type SealStatus = 'sealed' | 'opening_requested' | 'open' | 'closed' | 'superseded';
export type BasisKind = 'tender' | 'award' | 'negotiated';
export type OpeningReason = 'variation' | 'claim' | 'dispute' | 'final_account' | 'audit' | 'other';
export type BasisMethod = 'original_basis' | 'cost_plus_markup' | 'agreed' | 'daywork';

export const OPENING_REASONS: OpeningReason[] = ['variation', 'claim', 'dispute', 'final_account', 'audit', 'other'];

export interface Finding {
  rule_id: string;
  code: string;
  severity: string;
  message: string;
}

export interface Policy {
  profile: string;
  enabled: boolean;
  term: string;
  methods: BasisMethod[];
  require_breakdown: boolean;
  require_receipt: boolean;
  require_both_parties: boolean;
  internal_read: boolean;
  retention_years: number;
  on_account_percent: number | null;
  attachment_presets: string[];
  citations: string[];
  tsa_configured: boolean;
}

export interface SealCheck {
  code: string;
  status: 'ok' | 'warning' | 'error' | 'info';
  message: string;
  blocking: boolean;
}

export interface SealPreview {
  project_id: string;
  source_boq_id: string;
  contract_id: string | null;
  label: string;
  currency: string;
  seal_total: string;
  award_value: string | null;
  positions: number;
  with_breakdown: number;
  markup_names: string[];
  checks: SealCheck[];
  can_seal: boolean;
  policy: Policy;
}

export interface SealCreate {
  source_boq_id: string;
  contract_id?: string | null;
  basis_kind: BasisKind;
  label: string;
  deposit_mode: 'platform' | 'external';
  request_receipt: boolean;
  attachment_document_ids?: string[];
}

export interface SealSummary {
  id: string;
  project_id: string;
  contract_id: string | null;
  contract_label: string;
  source_boq_id: string | null;
  label: string;
  basis_kind: BasisKind;
  status: SealStatus;
  deposit_mode: string;
  profile: string;
  sealed_at: string;
  sealed_by_name: string;
  award_total: string;
  currency: string;
  content_hash: string;
  tsa_authority: string | null;
  receipt_status: 'none' | 'requested' | 'signed' | 'external';
  openings: number;
  positions: number;
  with_breakdown: number;
  supersedes_id: string | null;
  superseded_by: { id: string; label: string; sealed_at: string; reason: string } | null;
  last_verified_at: string | null;
  last_verified_ok: boolean | null;
}

export interface Attachment {
  id: string;
  document_id: string | null;
  name: string;
  kind: string;
  file_hash: string;
}

export interface Receipt {
  id: string;
  kind: 'signing' | 'external';
  signing_session_id: string | null;
  external_reference: string;
  status: string;
  signed_at: string | null;
  created_at: string;
}

export interface SealDetail extends SealSummary {
  attachments: Attachment[];
  receipts: Receipt[];
  findings: Finding[];
  can_read_contents: boolean;
  open_opening_id: string | null;
  retention_until: string | null;
  supersede_reason: string;
  policy: Policy;
}

export interface Kpis {
  seals: number;
  awaiting_receipt: number;
  openings_in_progress: number;
  openings_this_year: number;
  positions_without_breakdown: number;
}

export interface Attendee {
  user_id?: string | null;
  name: string;
  organisation: string;
  role: string;
  side: 'internal' | 'counterparty';
  present?: boolean;
}

export interface Opening {
  id: string;
  seal_id: string;
  seal_label: string;
  requested_by_name: string;
  reason: OpeningReason;
  reference_label: string;
  scope: 'full' | 'positions';
  scope_ordinals: string[];
  attendees: Attendee[];
  one_party_reason: string;
  status: 'requested' | 'open' | 'closed' | 'halted';
  requested_at: string;
  opened_at: string | null;
  closed_at: string | null;
  hash_check: 'ok' | 'mismatch' | null;
  hash_seen: string | null;
  minutes_document_id: string | null;
  positions_viewed: string[];
  findings: Finding[];
}

export interface OpeningCreate {
  reason: OpeningReason;
  reference_label: string;
  reference_type?: string;
  scope: 'full' | 'positions';
  scope_ordinals: string[];
  attendees: Attendee[];
  one_party_reason: string;
}

export interface SealEvent {
  id: string;
  seal_id: string;
  opening_id: string | null;
  event_type: string;
  actor_name: string;
  actor_organisation: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface SealedResource {
  kind: string;
  code: string;
  description: string;
  unit: string;
  consumption: string;
  unit_cost: string;
  price_date: string;
  quote_ref: string;
}

export interface SealedPosition {
  ordinal: string;
  parent_ordinal: string | null;
  description: string;
  unit: string;
  quantity: string;
  unit_rate: string;
  total: string;
  resources: SealedResource[];
}

export interface SealedMarkup {
  key: string;
  name: string;
  category: string;
  markup_type: string;
  percentage: string;
  apply_to: string;
  is_active: boolean;
  scope_ordinal: string | null;
}

export interface Contents {
  seal_id: string;
  content_hash: string;
  payload: {
    estimate: { name: string; currency: string; base_date: string };
    positions: SealedPosition[];
    markups: SealedMarkup[];
  };
  scope_ordinals: string[] | null;
}

export interface ResourceChange {
  code: string;
  consumption?: string | null;
  unit_cost?: string | null;
  note?: string;
}

export interface ResourceAddition {
  kind: string;
  code: string;
  description: string;
  unit: string;
  consumption: string;
  unit_cost: string;
  price_date: string;
  quote_ref: string;
  note?: string;
}

export interface DeriveRequest {
  position_ordinal: string;
  quantity?: string | null;
  changes: ResourceChange[];
  additions: ResourceAddition[];
  removals: string[];
  current_unit_costs: Record<string, string>;
  agreed_rate?: string | null;
}

export interface DerivedLine {
  code: string;
  description: string;
  unit: string;
  consumption: string;
  unit_cost: string;
  amount: string;
  origin?: 'sealed' | 'new';
  consumption_changed?: boolean;
  unit_cost_changed?: boolean;
  sealed_consumption?: string;
  sealed_unit_cost?: string;
  note?: string;
}

export interface MarkupStep {
  key: string;
  name: string;
  percentage: string;
  amount: string;
}

export interface DeriveResultBody {
  ordinal: string;
  description: string;
  unit: string;
  quantity: string;
  sealed_lines: DerivedLine[];
  changed_lines: DerivedLine[];
  sealed_net: string;
  sealed_rate: string;
  changed_net: string;
  original_basis_rate: string;
  cost_plus_net: string | null;
  cost_plus_rate: string | null;
  markup_steps: MarkupStep[];
  methods: { method: BasisMethod; rate: string; total: string }[];
}

export interface DeriveResult {
  seal_id: string;
  result: DeriveResultBody;
  findings: Finding[];
  methods_order: BasisMethod[];
  citations: string[];
}

export interface DerivationCreate extends DeriveRequest {
  reference_label: string;
  description?: string;
  basis_method?: BasisMethod | null;
  variation_request_id?: string | null;
  write_to_variation_bill?: boolean;
}

export interface Derivation {
  id: string;
  seal_id: string;
  position_ordinal: string;
  reference_label: string;
  description: string;
  quantity: string;
  basis_method: BasisMethod | null;
  chosen_rate: string | null;
  created_at: string;
  findings: Finding[];
}

export interface VerifyResult {
  seal_id: string;
  ok: boolean;
  sealed_hash: string;
  actual_hash: string;
  verified_at: string;
}

const qs = (params: Record<string, string | null | undefined>) => {
  const parts = Object.entries(params)
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`);
  return parts.length ? `?${parts.join('&')}` : '';
};

export const archiveApi = {
  policy: (projectId: string) => apiGet<Policy>(`${BASE}/policy${qs({ project_id: projectId })}`),
  seals: async (projectId?: string) =>
    (await apiGet<{ items: SealSummary[] }>(`${BASE}/seals${qs({ project_id: projectId })}`)).items,
  kpis: (projectId?: string) => apiGet<Kpis>(`${BASE}/kpis${qs({ project_id: projectId })}`),
  seal: (id: string) => apiGet<SealDetail>(`${BASE}/seals/${id}`),
  preview: (body: SealCreate) => apiPost<SealPreview, SealCreate>(`${BASE}/seals/preview`, body),
  create: (body: SealCreate) => apiPost<SealDetail, SealCreate>(`${BASE}/seals`, body),
  supersede: (id: string, body: SealCreate & { reason: string }) =>
    apiPost<SealDetail, SealCreate & { reason: string }>(`${BASE}/seals/${id}/supersede`, body),
  verify: (id: string) => apiPost<VerifyResult>(`${BASE}/seals/${id}/verify`, {}),
  checkAttachment: (id: string, attachmentId: string) =>
    apiPost<{ ok: boolean; sealed_hash: string; actual_hash: string }>(
      `${BASE}/seals/${id}/attachments/${attachmentId}/verify`,
      {},
    ),
  contents: (id: string) => apiGet<Contents>(`${BASE}/seals/${id}/contents`),
  positionViewed: (id: string, ordinal: string) =>
    apiPost<void>(`${BASE}/seals/${id}/positions/${encodeURIComponent(ordinal)}/viewed`, {}),
  events: async (sealId?: string, projectId?: string) =>
    (
      await apiGet<{ items: SealEvent[] }>(
        sealId ? `${BASE}/seals/${sealId}/events` : `${BASE}/events${qs({ project_id: projectId })}`,
      )
    ).items,
  openings: async (params: { projectId?: string; sealId?: string }) =>
    (
      await apiGet<{ items: Opening[] }>(
        `${BASE}/openings${qs({ project_id: params.projectId, seal_id: params.sealId })}`,
      )
    ).items,
  requestOpening: (sealId: string, body: OpeningCreate) =>
    apiPost<Opening, OpeningCreate>(`${BASE}/seals/${sealId}/openings`, body),
  startOpening: (openingId: string, present: string[]) =>
    apiPost<Opening>(`${BASE}/openings/${openingId}/start`, { present }),
  closeOpening: (openingId: string) => apiPost<Opening>(`${BASE}/openings/${openingId}/close`, {}),
  requestReceipt: (sealId: string) => apiPost<Receipt>(`${BASE}/seals/${sealId}/receipt`, {}),
  externalReceipt: (sealId: string, reference: string) =>
    apiPost<Receipt>(`${BASE}/seals/${sealId}/receipt/external`, { external_reference: reference }),
  derive: (sealId: string, body: DeriveRequest) =>
    apiPost<DeriveResult, DeriveRequest>(`${BASE}/seals/${sealId}/derive`, body),
  recordDerivation: (sealId: string, body: DerivationCreate) =>
    apiPost<Derivation, DerivationCreate>(`${BASE}/seals/${sealId}/derivations`, body),
  derivations: async (sealId: string) =>
    (await apiGet<{ items: Derivation[] }>(`${BASE}/derivations${qs({ seal_id: sealId })}`)).items,
  chooseMethod: (derivationId: string, method: BasisMethod) =>
    apiPost<Derivation>(`${BASE}/derivations/${derivationId}/method`, { basis_method: method }),
  variationFindings: (variationRequestId: string) =>
    apiGet<Finding[]>(`${BASE}/variations/${variationRequestId}/findings`),
  downloadPackage: (sealId: string) =>
    downloadWithAuth(`/api${BASE}/seals/${sealId}/package`, `sealed-estimate-${sealId.slice(0, 8)}.zip`),
};

/** First 8 and last 8 hex digits, the way a fingerprint is read aloud at a meeting. */
export function shortHash(hash: string): string {
  return hash.length > 20 ? `${hash.slice(0, 8)}…${hash.slice(-8)}` : hash;
}
